/* Un Core minuscule et honnête pour les tests node de l'explorateur de variantes (studio de présentation, Slice 18).

   Ce double connaît les règles qui comptent pour l'interface, dites par `docs/presentation-studio.md` › *Variant graph and operations contract* :
   numéros monotones jamais réutilisés, sous-arbre archivé d'un bloc, jeton de confirmation lié à l'ensemble, aux titres et à la révision (périmé =
   409), variante active protégée, `variant_in_playback`, plafond de 64 vivantes, révision attendue (`stale_revision`). Il répond aux mêmes routes
   du relais que la vraie page appelle, avec les mêmes formes. Ce n'est PAS la preuve de Core (`test_presentation_studio_variants_*`) ni du relais
   (`test_presentation_studio_variants_routes`) : c'est le banc qui permet de lier chaque geste de l'interface à une réponse réaliste. */
'use strict';

const BASE='/api/presentation-studio/presentations';
const PID='pst_'+'0'.repeat(31)+'1';
const vid=n=>'psv_'+String(n).padStart(32,'0');
const iso=(minutesAgo,now)=>new Date((now||Date.UTC(2026,9,8,12,0,0))-minutesAgo*60000).toISOString();

function makeWorld(env,options){
  const o=options||{};
  const world={pid:PID,title:o.title||'Atelier du cadran',revision:5,counter:0,active:null,live:[],archived:[],docs:new Map(),art:new Map(),
    playingVariant:null,runningNow:false,calls:[],failNext:[],delays:[],secret:'s3cret',tokenTtlS:600,now:()=>env.timers.now(),epoch:()=>Math.floor(env.timers.now()/1000),
    scenesPerVariant:o.scenes||3};
  world.add=(parent,extra)=>{
    world.counter+=1;
    const n=world.counter;
    const node=Object.assign({variant_id:vid(n),variant_number:n,title:'Variante '+n,parent_variant_id:parent?vid(parent):null,rationale:'',created_by:'user',
      sources:parent?[vid(parent)]:[],preview_id:null,revision:1,created_at:iso(Math.max(1,60-n),world.now()),updated_at:iso(1,world.now()),
      scene_count:world.scenesPerVariant,active:false,state:'live'},extra||{});
    world.live.push(node);
    if(!world.active)world.active=node.variant_id;
    return node;
  };
  world.byId=id=>world.live.find(n=>n.variant_id===id)||world.archived.find(n=>n.variant_id===id)||null;
  world.kids=(id,list)=>(list||world.live).filter(n=>n.parent_variant_id===id);
  world.subtree=(id,list)=>{const out=[],stack=[id];while(stack.length){const cur=stack.pop();out.push(cur);for(const k of world.kids(cur,list))stack.push(k.variant_id)}return out};
  world.graph=()=>({presentation_id:PID,revision:world.revision,variant_counter:world.counter,active_variant_id:world.active,archived_count:world.archived.length,
    reconciliation:null,nodes:[...world.live.map(n=>Object.assign({},n,{active:n.variant_id===world.active,state:'live'})),
      ...world.archived.map(n=>Object.assign({},n,{active:false,state:'archived',archived_at:iso(5,world.now()),archived_by:'user',batch_id:'psb_1'}))]});
  world.doc=(id)=>{
    const node=world.live.find(n=>n.variant_id===id);
    if(!node)return null;
    if(world.docs.has(id))return world.docs.get(id);
    const scenes=Array.from({length:node.scene_count},(_,i)=>({scene_id:'pss_'+String(i+1).padStart(12,'0'),prefab:{id:'lab.dial',version:1},title:`Scène ${i+1} de ${node.variant_number}`,
      section:['Ouverture','Chiffres','Conclusion','Annexe'][i%4],props:{title:'T'+i},data:{body:'B'+i},controls:[],anchors:[],preview:{caption:'',alt:''},
      source_revision:1,last_valid_pin:null}));
    return {schema:'jarvis.presentation_studio.variant',variant_id:id,variant_number:node.variant_number,title:node.title,scenes,score_id:'psr_'+'0'.repeat(12),
      art_direction_id:'psd_'+'0'.repeat(12),revision:node.revision,parent_variant_id:node.parent_variant_id};
  };
  world.token=(plan,exp)=>`psk_${exp}.`+Buffer.from(JSON.stringify([world.secret,plan.revision,plan.root,plan.rows,plan.activate,exp])).toString('base64').slice(0,40);
  world.plan=(id,activate)=>{
    const ids=world.subtree(id);
    const rows=ids.map(i=>world.byId(i)).sort((a,b)=>a.variant_number-b.variant_number).map(n=>[n.variant_id,n.variant_number,n.title]);
    const remaining=world.live.filter(n=>!ids.includes(n.variant_id));
    const includesActive=ids.includes(world.active);
    const node=world.byId(id);
    const suggested=includesActive?(node.parent_variant_id&&!ids.includes(node.parent_variant_id)?node.parent_variant_id:(remaining[0]&&remaining[0].variant_id)||null):null;
    let blocked=null;
    if(!remaining.length)blocked='presentation_studio_active_variant_protected';
    else if(includesActive&&!activate)blocked='presentation_studio_active_variant_protected';
    return {revision:world.revision,root:id,rows,activate:activate||null,includesActive,suggested,blocked,ids};
  };

  const json=(status,body)=>({status,body});
  const err=(status,code,message)=>json(status,{error:{code,message:message||code}});
  /* Un échec programmé ne se consomme que sur la requête qu'il vise (`match`), jamais sur celle qui passe devant. */
  const fail=(url,rec)=>{const i=world.failNext.findIndex(f=>!f.match||f.match(url,rec));return i<0?null:world.failNext.splice(i,1)[0]};
  const parse=(url)=>{
    const u=url.split('?')[0];
    const m=u.startsWith(BASE)?u.slice(BASE.length):null;
    return m===null?null:m.split('/').filter(Boolean).map(decodeURIComponent);
  };
  const check=(body)=>{
    if(body&&body.expected_revision!==undefined&&body.expected_revision!==world.revision)return err(409,'presentation_studio_stale_revision','stale');
    return null;
  };
  const handle=(url,rec,body)=>{
    world.calls.push({method:rec.method,url,body});
    const forced=fail(url,rec);
    if(forced)return forced.reply||json(forced.status||500,forced.body||{error:{code:forced.code||'boom',message:'boom'}});
    if(url.startsWith('/api/presentation-studio/playback'))return json(200,{state:world.runningNow?{running:true,phase:'playing'}:{running:false,phase:'idle'}});
    if(url.startsWith('/api/presentation-studio/explorer/state'))return json(200,{});
    const seg=parse(url);
    if(!seg||seg[0]!==PID)return err(404,'presentation_studio_unknown_presentation','unknown presentation');
    const method=rec.method;
    if(seg.length===1&&method==='GET')return json(200,{presentation:{presentation_id:PID,title:world.title,active_variant_id:world.active,revision:world.revision}});
    if(seg[1]==='graph')return json(200,world.graph());
    if(seg[1]==='variants'&&seg.length===2&&method==='POST'){
      const stale=check(body);if(stale)return stale;
      if(world.live.length>=64)return err(409,'presentation_studio_limit_reached','64 live variants at most');
      const source=world.live.find(n=>n.variant_id===(body.source_variant_id||world.active));
      if(!source)return err(404,'presentation_studio_unknown_variant','unknown');
      if(typeof body.title!=='string'||!body.title.trim())return err(400,'presentation_studio_invalid','title');
      world.revision+=1;
      const node=world.add(source.variant_id,{title:body.title,rationale:body.rationale||'',created_by:'user',scene_count:source.scene_count});
      if(body.activate)world.active=node.variant_id;
      return json(201,{node:Object.assign({},node),activated:!!body.activate,source_variant_id:source.variant_id,presentation_revision:world.revision});
    }
    const id=seg[2];
    if(seg[1]==='variants'&&seg.length===3&&method==='GET'){
      const doc=world.doc(id);
      return doc?json(200,doc):err(404,'presentation_studio_unknown_variant','unknown variant');
    }
    if(seg[1]==='variants'&&seg[3]==='art-direction'&&method==='GET'){
      const art=world.art.get(id);
      return art?json(200,{art_direction:art}):err(404,'presentation_studio_unknown_art_direction','none');
    }
    if(seg[1]==='variants'&&method==='POST'){
      const op=seg[3];
      const stale=check(body);
      if(op==='activate'){
        if(stale)return stale;
        if(!world.live.find(n=>n.variant_id===id))return err(404,'presentation_studio_unknown_variant','unknown');
        if(world.active!==id){world.active=id;world.revision+=1}
        return json(200,{variant_id:id,changed:true});
      }
      if(op==='rename'){
        if(stale)return stale;
        const node=world.live.find(n=>n.variant_id===id);
        if(!node)return err(404,'presentation_studio_unknown_variant','unknown');
        node.title=body.title;node.revision+=1;world.docs.delete(id);
        return json(200,{changed:true,variant_id:id,title:node.title});
      }
      if(op==='archive-plan'){
        const node=world.live.find(n=>n.variant_id===id);
        if(!node)return err(404,'presentation_studio_unknown_variant','unknown');
        const plan=world.plan(id,body.activate_variant_id);
        if(world.playingVariant&&plan.ids.includes(world.playingVariant))return err(409,'presentation_studio_variant_in_playback','in playback');
        if(world.archived.length+plan.ids.length>128)return err(409,'presentation_studio_limit_reached','archive full');
        const exp=world.epoch()+world.tokenTtlS;
        return json(200,{plan:{presentation_id:PID,revision:plan.revision,root_variant_id:id,
          affected:plan.rows.map(r=>({variant_id:r[0],variant_number:r[1],title:r[2]})),count:plan.rows.length,includes_active:plan.includesActive,
          active_variant_id:world.active,activate_variant_id:plan.activate,requires_new_active:plan.includesActive&&!plan.activate,suggested_active:plan.suggested,
          blocked:plan.blocked,blocked_reason:plan.blocked?'blocked':''},confirmation:plan.blocked?null:world.token(plan,exp),expires_in_s:plan.blocked?null:world.tokenTtlS});
      }
      if(op==='archive'){
        if(typeof body.confirmation!=='string')return err(400,'presentation_studio_confirmation_required','needs a plan');
        if(world.playingVariant&&world.subtree(id).includes(world.playingVariant))return err(409,'presentation_studio_variant_in_playback','in playback');
        const plan=world.plan(id,body.activate_variant_id);
        const exp=Number(body.confirmation.split('.')[0].replace('psk_',''));
        if(plan.blocked)return err(409,'presentation_studio_active_variant_protected','protected');
        if(body.confirmation!==world.token(plan,exp)||exp<world.epoch())return err(409,'presentation_studio_confirmation_stale','stale token');
        const moved=plan.ids.map(i=>world.byId(i));
        world.live=world.live.filter(n=>!plan.ids.includes(n.variant_id));
        world.archived.push(...moved);
        if(plan.ids.includes(world.active))world.active=body.activate_variant_id;
        world.revision+=1;
        return json(200,{archived:plan.rows.map(r=>({variant_id:r[0],variant_number:r[1],title:r[2]})),count:plan.rows.length,root_variant_id:id,
          root_variant_number:world.byId(id).variant_number,active_variant_id:world.active,presentation_revision:world.revision,restorable:true});
      }
      if(op==='restore'){
        if(stale)return stale;
        const node=world.archived.find(n=>n.variant_id===id);
        if(!node)return err(409,'presentation_studio_not_archived','not archived');
        const chain=[];
        for(let cur=node;cur;cur=world.archived.find(n=>n.variant_id===cur.parent_variant_id))chain.unshift(cur);
        const back=new Set(chain.map(n=>n.variant_id));
        if(body.with_descendants)for(const i of world.subtree(id,world.archived))back.add(i)
        if(world.live.length+back.size>64)return err(409,'presentation_studio_limit_reached','too many');
        const moving=world.archived.filter(n=>back.has(n.variant_id));
        world.archived=world.archived.filter(n=>!back.has(n.variant_id));
        world.live.push(...moving);
        world.revision+=1;
        return json(200,{restored:moving.map(n=>({variant_id:n.variant_id,variant_number:n.variant_number})),count:moving.length,variant_number:node.variant_number});
      }
    }
    return err(404,'no_route','unscripted '+method+' '+url);
  };
  /* Un retard programmé s'applique à la réponse, pas à l'effet : Core a agi, la réponse arrive tard. */
  env.route(url=>url.startsWith(BASE)||url.startsWith('/api/presentation-studio/playback')||url.startsWith('/api/presentation-studio/explorer'),(url,rec,body)=>{
    const reply=handle(url,rec,body);
    const i=world.delays.findIndex(d=>!d.match||d.match(url,rec));
    if(i>=0&&reply&&!reply.hang)return Object.assign({},reply,{delay:world.delays.splice(i,1)[0].ms});
    return reply;
  });
  return world;
}
module.exports={makeWorld,PID,vid,iso,BASE};
