/* Éléments de l'explorateur de variantes du Studio : l'arbre virtualisé, les formulaires des boîtes de dialogue et le canal de commandes de la page
   (handoff jarvis-interactive-presentation-studio, Slice 18).

   Ce fichier ne garde AUCUN état de présentation : le contrôleur (`control_center_presentation_studio_explorer.js`) lui passe un « kit » (DOM, horloge,
   aides de rendu) et des rappels (`hooks`) ; il ne lit ni ne modifie le graphe. Mêmes marqueurs de page que le contrôleur ; il passe entre le noyau
   pur et lui, et publie `window.JarvisStudioExplorerWidgets` (et `module.exports` pour node).

   - `createTreeView` : un arbre ARIA (`role=tree`, `treeitem` à plat avec `aria-level`/`aria-posinset`/`aria-setsize`, tabindex itinérant) rendu en
     fenêtre glissante : seules les lignes visibles (plus une marge et la ligne focalisée) existent dans le DOM, réutilisées par identifiant, dans
     l'ordre de l'arbre (les lecteurs d'écran suivent le DOM) ;
   - `fillTitleDialog` / `fillArchiveDialog` : le formulaire « Brancher » / « Renommer » et la boîte d'archivage (ensemble exact, variante qui remplace
     l'active, jeton et compte à rebours) ; tout texte d'auteur y est écrit par `textContent` ;
   - `createCommandChannel` : le long-poll de la page (`GET/POST /api/presentation-studio/explorer/commands`), frère de celui du plein écran. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,checkTitle,checkRationale,rationaleBytes,describeRefusal,sameSet,MAX_RATIONALE_BYTES,COMMAND_ROUTE,ROW_H,MAX_DEPTH_SHOWN,INDENT_PX,LONG_PRESS_MS,windowOf,flatten,treeKey,relativeTime,creatorLabel}=Core;
  const COMMAND_POLL_WAIT_S=25;
  const COMMAND_POLL_TIMEOUT_MS=30000;
  const COMMAND_MIN_GAP_MS=1000;
  function describe(error){return cleanLine(error&&error.message||String(error||'erreur inconnue'),200)}

    /* -------------------------------------------------------------- l'arbre (rendu virtualisé, lignes réutilisées par id) */
    function createTreeView(kit,spec){
      const {doc,el,attrs,button,icon,uid,later,cancelLater,frame,now,stats}=kit;
      const box=el('div','jvx-tree');
      attrs(box,{role:'tree','aria-label':spec.label,'aria-multiselectable':'false'});
      const spacer=el('div','jvx-spacer');
      const empty=el('div','jvx-empty');
      box.appendChild(spacer);box.appendChild(empty);
      const pool=new Map();
      let rows=[],forest=null,ctx={};
      let scheduled=false,longPress=null;
      const indexOf=id=>rows.findIndex(r=>r.id===id);
      let playingSet=null;
      /* Les lignes de lignée : un trait vertical par colonne dont l'ancêtre a encore un frère à venir, puis le coude du nœud (vertical jusqu'au
         milieu s'il est le dernier de sa fratrie, jusqu'en bas sinon, et un trait horizontal vers lui). Du dessin pur, en dégradés. */
      function paintRail(rail,row){
        const layers=[];
        const tone='linear-gradient(var(--jvx-line-strong),var(--jvx-line-strong))';
        const x=c=>c*INDENT_PX+Math.floor(INDENT_PX/2);
        const limit=Math.min(row.depth,MAX_DEPTH_SHOWN);
        for(let c=0;c<row.trail.length&&c<limit-1;c++){
          if(row.trail[c])layers.push([tone,'1px 100%',`${x(c)}px 0`]);
        }
        if(row.depth>=1&&row.depth<=MAX_DEPTH_SHOWN){
          const c=row.depth-1;
          layers.push([tone,row.last?'1px 50%':'1px 100%',`${x(c)}px 0`]);
          layers.push([tone,`${INDENT_PX-Math.floor(INDENT_PX/2)}px 1px`,`${x(c)}px 50%`]);
        }
        rail.style.backgroundImage=layers.map(l=>l[0]).join(',');
        rail.style.backgroundSize=layers.map(l=>l[1]).join(',');
        rail.style.backgroundPosition=layers.map(l=>l[2]).join(',');
      }
      function describeRow(row){
        const node=row.node;
        const bits=[`Variante ${node.variant_number}`,cleanLine(node.title,80)];
        if(ctx.activeId===row.id)bits.push('active');
        if(playingSet&&playingSet.has(row.id))bits.push('en cours de lecture');
        if(row.hasChildren)bits.push(`${row.descendants} sous-branche${row.descendants>1?'s':''}`);
        if(node.state==='archived')bits.push('archivée');
        return bits.join(', ');
      }
      function paintRow(node,row,top){
        const v=row.node;
        node.dataset.id=row.id;
        node.style.top=`${top}px`;
        node.setAttribute('aria-level',String(row.depth+1));
        node.setAttribute('aria-posinset',String(row.posInSet));
        node.setAttribute('aria-setsize',String(row.setSize));
        node.setAttribute('aria-selected',ctx.selectedId===row.id?'true':'false');
        if(row.hasChildren)node.setAttribute('aria-expanded',row.expanded?'true':'false');else node.removeAttribute('aria-expanded');
        node.setAttribute('aria-label',describeRow(row));
        node.setAttribute('tabindex',ctx.focusId===row.id?'0':'-1');
        node.dataset.active=ctx.activeId===row.id?'true':'false';
        const rationale=cleanLine(v.rationale,600);
        node.setAttribute('title',rationale?rationale:(v.state==='archived'?'Variante archivée':'Pas de raison notée pour cette variante'));
        const parts=node._parts;
        const indent=Math.min(row.depth,MAX_DEPTH_SHOWN)*INDENT_PX;
        parts.rail.style.width=`${indent}px`;
        parts.rail.hidden=indent===0;
        paintRail(parts.rail,row);
        parts.depth.hidden=row.depth<=MAX_DEPTH_SHOWN;
        if(row.depth>MAX_DEPTH_SHOWN)parts.depth.textContent=`↳${row.depth}`;
        const twist=parts.twist;
        twist.hidden=!row.hasChildren;parts.gap.hidden=row.hasChildren;
        if(row.hasChildren){
          twist.setAttribute('aria-expanded',row.expanded?'true':'false');
          twist.setAttribute('aria-label',`${row.expanded?'Replier':'Déplier'} ${row.descendants>1?`les ${row.descendants} sous-branches`:'la sous-branche'} de la variante ${v.variant_number}`);
        }
        parts.num.textContent=`#${v.variant_number}`;
        const title=cleanLine(v.title,80)||'(sans titre)';
        if(parts.title.textContent!==title)parts.title.textContent=title;
        const meta=[];
        const when=relativeTime(v.created_at,now());
        if(when)meta.push(when);
        const who=creatorLabel(v.created_by);
        if(who)meta.push(who);
        if(v.state==='archived'){if(row.outside)meta.push('sous-branche d\'une variante vivante');if(v.problem)meta.push('fichier illisible')}
        else if(Number.isFinite(v.scene_count))meta.push(`${v.scene_count} scène${v.scene_count>1?'s':''}`);
        if(row.cyclic)meta.push('parenté incohérente');
        parts.meta.textContent=meta.join(' · ');
        const flag=playingSet&&playingSet.has(row.id)?'playing':v.problem?'issue':ctx.activeId===row.id?'active':'';
        parts.flag.hidden=!flag;parts.flag.dataset.flag=flag;
        parts.flag.textContent=flag==='playing'?'En lecture':flag==='issue'?'À vérifier':flag==='active'?'Actif':'';
      }
      function makeRow(){
        const node=el('div','jvx-row');
        attrs(node,{role:'treeitem',id:uid('row')});
        const parts={
          rail:el('span','jvx-rail'),depth:el('span','jvx-depth'),
          twist:button(null,'jvx-twist',null,{icon:'chevron',attrs:{tabindex:'-1'}}),gap:el('span','jvx-twist-gap'),
          num:el('span','jvx-num'),title:el('span','jvx-rowtitle jvx-bidi'),meta:el('span','jvx-rowmeta'),flag:el('span','jvx-flag'),
        };
        parts.title.setAttribute('dir','auto');
        const text=el('span','jvx-rowtext');
        text.appendChild(parts.title);text.appendChild(parts.meta);
        for(const part of [parts.rail,parts.depth,parts.twist,parts.gap,parts.num,text,parts.flag])node.appendChild(part);
        node._parts=parts;
        return node;
      }
      function paint(){
        scheduled=false;
        const t0=now();
        playingSet=ctx.playing||null;
        const total=rows.length;
        empty.hidden=total>0;
        spacer.style.height=`${total*ROW_H}px`;
        spacer.hidden=total===0;
        const view=windowOf(total,box.scrollTop||0,box.clientHeight||ROW_H*8,ROW_H);
        const wanted=new Set();
        const focusIndex=ctx.focusId?indexOf(ctx.focusId):-1;
        for(let i=view.start;i<view.end;i++)wanted.add(i);
        if(focusIndex>=0)wanted.add(focusIndex);
        const keep=new Set();
        /* L'ordre du DOM est celui de l'arbre (les lecteurs d'écran le suivent), même si les lignes sont positionnées en absolu. */
        const order=Array.from(wanted).sort((a,b)=>a-b);
        let cursor=spacer.firstChild;
        for(const i of order){
          const row=rows[i];
          keep.add(row.id);
          let node=pool.get(row.id);
          if(!node){node=makeRow();pool.set(row.id,node)}
          if(node===cursor)cursor=cursor.nextSibling;
          else spacer.insertBefore(node,cursor);
          paintRow(node,row,i*ROW_H);
        }
        for(const [id,node] of Array.from(pool)){
          if(!keep.has(id)){if(node.contains(doc.activeElement)){}pool.delete(id);node.remove()}
        }
        stats.paints+=1;stats.lastPaintMs=now()-t0;
      }
      function schedule(){if(scheduled)return;scheduled=true;frame(paint)}
      box.addEventListener('scroll',schedule);
      function rowOfEvent(event){
        const item=event.target&&event.target.closest?event.target.closest('[role="treeitem"]'):null;
        return item&&item.dataset?item.dataset.id:null;
      }
      box.addEventListener('click',event=>{
        const id=rowOfEvent(event);
        if(!id)return;
        const twist=event.target.closest('.jvx-twist');
        if(twist){spec.onToggle(id);return}
        spec.onSelect(id,{pointer:true});
      });
      box.addEventListener('keydown',event=>{
        const id=rowOfEvent(event)||ctx.focusId;
        if(!id||event.target&&event.target.closest&&event.target.closest('.jvx-twist')&&event.key===' ')return;
        spec.onKey(event,id,rows,indexOf(id));
      });
      box.addEventListener('focusin',event=>{const id=rowOfEvent(event);if(id)spec.onFocus(id)});
      box.addEventListener('contextmenu',event=>{
        const id=rowOfEvent(event);
        if(!id)return;
        event.preventDefault();
        spec.onMenu(id,{x:event.clientX,y:event.clientY,pointer:event.clientX!==0||event.clientY!==0});
      });
      box.addEventListener('pointerdown',event=>{
        if(event.pointerType!=='touch'&&event.pointerType!=='pen')return;
        const id=rowOfEvent(event);
        if(!id)return;
        cancelLongPress();
        longPress={id,x:event.clientX,y:event.clientY,timer:later(()=>{longPress=null;spec.onMenu(id,{x:event.clientX,y:event.clientY,pointer:true,touch:true})},LONG_PRESS_MS)};
      });
      const cancelLongPress=()=>{if(longPress){cancelLater(longPress.timer);longPress=null}};
      for(const type of ['pointerup','pointercancel','pointerleave'])box.addEventListener(type,cancelLongPress);
      box.addEventListener('pointermove',event=>{if(longPress&&(Math.abs(event.clientX-longPress.x)>8||Math.abs(event.clientY-longPress.y)>8))cancelLongPress()});
      return {
        element:box,
        setData(next){
          forest=next.forest;ctx=next.ctx;
          rows=forest?flatten(forest,spec.collapsed()):[];
          empty.textContent=next.emptyText||'';
          paint();
        },
        repaint:paint,rows:()=>rows,indexOf,
        ensureVisible(id){
          const i=indexOf(id);
          if(i<0)return;
          const height=box.clientHeight||ROW_H*8,top=i*ROW_H;
          if(top<box.scrollTop)box.scrollTop=top;
          else if(top+ROW_H>box.scrollTop+height)box.scrollTop=top+ROW_H-height;
          paint();
        },
        focus(id){
          this.ensureVisible(id);
          const node=pool.get(id);
          if(node)node.focus({preventScroll:true});
          return !!node&&doc.activeElement===node;
        },
        rowElement:id=>pool.get(id)||null,
        poolSize:()=>pool.size,
        destroy(){cancelLongPress();pool.clear()},
      };
    }


    /* Formulaire titre (+ raison) partagé par « Brancher » et « Renommer ». */
    function fillTitleDialog(kit,dlg,config,hooks){
      const {doc,el,attrs,dialogButton}=kit;
      const box=dlg.box;
      const title=el('h2','',config.heading);title.id='jvxDialogTitle';
      box.appendChild(title);
      if(config.intro)box.appendChild(el('p','',config.intro));
      const form=el('form');
      form.addEventListener('submit',event=>{event.preventDefault();submit()});
      const f1=el('div','jvx-field');
      const l1=el('label','','Titre');l1.setAttribute('for','jvxTitleInput');
      const input=el('input');attrs(input,{type:'text',id:'jvxTitleInput',maxlength:'400',autocomplete:'off',spellcheck:'false','aria-describedby':'jvxTitleError'});
      input.value=config.title;
      const err1=el('div','jvx-error');err1.id='jvxTitleError';err1.setAttribute('role','alert');
      f1.appendChild(l1);f1.appendChild(input);f1.appendChild(err1);
      form.appendChild(f1);
      let area=null,err2=null,activateBox=null;
      if(config.withRationale){
        const f2=el('div','jvx-field');
        const l2=el('label','','Pourquoi cette branche ? (facultatif)');l2.setAttribute('for','jvxRationaleInput');
        area=el('textarea');attrs(area,{id:'jvxRationaleInput',maxlength:'1200','aria-describedby':'jvxRationaleHint jvxRationaleError'});
        const hint=el('div','jvx-hint');hint.id='jvxRationaleHint';
        err2=el('div','jvx-error');err2.id='jvxRationaleError';err2.setAttribute('role','alert');
        f2.appendChild(l2);f2.appendChild(area);f2.appendChild(hint);f2.appendChild(err2);
        form.appendChild(f2);
        const paintHint=()=>{hint.textContent=`${Array.from(area.value).length}/600 caractères · ${rationaleBytes(cleanLine(area.value,700))}/${MAX_RATIONALE_BYTES} octets`};
        area.addEventListener('input',paintHint);paintHint();
        const check=el('label','jvx-check');
        activateBox=el('input');activateBox.type='checkbox';
        check.appendChild(activateBox);check.appendChild(el('span','','Activer la nouvelle branche tout de suite'));
        form.appendChild(check);
      }
      const row=el('div','jvx-dialog-actions');
      const cancel=dialogButton('Annuler',()=>hooks.cancel());
      const ok=dialogButton(config.confirm,null,{primary:true});ok.setAttribute('type','submit');
      row.appendChild(cancel);row.appendChild(ok);
      form.appendChild(row);
      box.appendChild(form);
      async function submit(){
        err1.textContent='';if(err2)err2.textContent='';
        const t=checkTitle(input.value);
        if(!t.ok){err1.textContent=t.message;input.focus();return}
        let r={ok:true,value:''};
        if(area){r=checkRationale(area.value);if(!r.ok){err2.textContent=r.message;area.focus();return}}
        if(config.unchanged&&t.value===config.title){hooks.close();return}
        dlg.busy=true;ok.setAttribute('aria-disabled','true');
        const success=await config.run({title:t.value,rationale:r.value,activate:!!(activateBox&&activateBox.checked)});
        dlg.busy=false;
        if(hooks.isCurrent()){
          if(success){
            /* La boîte se ferme D'ABORD (le reste de l'espace n'est plus inerte, le focus lui est rendu), puis la page relit le graphe et déplace la sélection. */
            hooks.close();
            if(typeof config.finish==='function')await config.finish(success);
          }
          else{ok.removeAttribute('aria-disabled');const note=hooks.notice();if(note)err1.textContent=note;input.focus()}
        }
      }
      input.focus();input.select();
      return dlg;
    }

    function fillArchiveDialog(kit,dlg,params,hooks){
      const {el,attrs,clear,now,every,dialogButton}=kit;
      const planFor=params.planFor;
      let model=params.model,activateId=params.activateId,planAt=now(),stale=null;
      const box=dlg.box;
      const paint=()=>{
        clear(box);
        const title=el('h2','',model.blocked?'Archivage impossible':`Archiver ${model.count} variante${model.count>1?'s':''} ?`);title.id='jvxDialogTitle';
        box.appendChild(title);
        const rootRow=model.rows.find(r=>r.id===model.root)||model.rows[0];
        const lead=rootRow?`#${rootRow.number} « ${rootRow.title||'(sans titre)'} »${model.count>1?` et ses ${model.count-1} sous-branche${model.count>2?'s':''}`:''}`:'Ces variantes';
        const intro=el('p','');
        intro.textContent=`${lead} quitte${model.count>1?'nt':''} l'arbre. Rien n'est supprimé : elles restent dans l'archive et se restaurent.`;
        box.appendChild(intro);
        if(stale)box.appendChild(Object.assign(el('div','jvx-warnbox',stale),{}));
        const list=el('ul','jvx-set');list.setAttribute('aria-label','Variantes qui seraient archivées');
        for(const row of model.rows){
          const li=el('li');
          li.appendChild(el('span','jvx-num',`#${row.number}`));
          const t=el('span','jvx-rowtitle jvx-bidi',row.title||'(sans titre)');t.setAttribute('dir','auto');li.appendChild(t);
          li.appendChild(el('span','jvx-sid',`psv_${row.short}…`));
          list.appendChild(li);
        }
        box.appendChild(list);
        if(model.includesActive||model.requiresNewActive){
          const set=el('fieldset','jvx-choice');
          set.appendChild(el('legend','',"La variante active est dans cette liste : choisissez celle qui la remplace."));
          if(!model.choices.length)set.appendChild(el('p','',"Aucune variante ne resterait : l'archivage est impossible."));
          for(const choice of model.choices){
            const label=el('label');
            const radio=el('input');attrs(radio,{type:'radio',name:'jvxActive',value:choice.id});
            radio.checked=choice.id===activateId;
            radio.addEventListener('change',()=>{activateId=choice.id;replan()});
            label.appendChild(radio);
            label.appendChild(el('span','jvx-num',`#${choice.number}`));
            const t=el('span','jvx-bidi',choice.title||'(sans titre)');t.setAttribute('dir','auto');label.appendChild(t);
            set.appendChild(label);
          }
          box.appendChild(set);
        }
        if(model.blocked)box.appendChild(el('div','jvx-warnbox',model.blockedReason));
        dlg.token=el('div','jvx-token');dlg.token.setAttribute('role','timer');
        box.appendChild(dlg.token);
        dlg.tick=()=>{
          if(!dlg.token||!dlg.ok)return;
          const gone=model.blocked||!model.token;
          if(gone){dlg.token.textContent='';dlg.ok.setAttribute('aria-disabled','true');dlg.recompute.hidden=true;return}
          const left=model.expiresInS===null?null:Math.max(0,Math.ceil((model.expiresInS*1000-(now()-planAt))/1000));
          const over=left!==null&&left<=0;
          dlg.token.setAttribute('data-state',over?'expired':'valid');
          dlg.token.textContent=over?"La confirmation a expiré : recalculez la liste pour la confirmer de nouveau."
            :left===null?'':`Confirmation valable encore ${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`;
          if(over)dlg.ok.setAttribute('aria-disabled','true');else dlg.ok.removeAttribute('aria-disabled');
          dlg.recompute.hidden=!over;
        };
        const row=el('div','jvx-dialog-actions');
        dlg.cancel=dialogButton('Annuler',()=>hooks.cancel());
        dlg.recompute=dialogButton('Recalculer',()=>replan());
        dlg.ok=dialogButton(model.count>1?`Archiver ${model.count} variantes`:'Archiver',()=>execute(),{primary:true,danger:true});
        row.appendChild(dlg.cancel);row.appendChild(dlg.recompute);row.appendChild(dlg.ok);
        box.appendChild(row);
        dlg.tick();
      };
      const replan=async()=>{
        if(dlg.busy)return;
        dlg.busy=true;
        const before=model;
        const done=await hooks.perform('plan','Calcul de la liste',async()=>{model=await planFor(activateId);return true});
        dlg.busy=false;
        if(!hooks.isCurrent())return;
        if(done&&!done.error){
          planAt=now();
          stale=before&&!sameSet(before.rows,model.rows)?`La liste a changé : ${before.count} → ${model.count} variante${model.count>1?'s':''}. Relisez-la avant de confirmer.`:null;
          paint();
          dlg.cancel.focus();
        }else{model=before;paint()}
      };
      const execute=async()=>{
        if(dlg.busy||!model.token||model.blocked||expired())return;      /* un jeton périmé ne part jamais : on le dit, on recalcule */
        dlg.busy=true;
        const count=model.count;
        const node=hooks.node();
        let answer=null;
        const body=Object.assign({confirmation:model.token},activateId?{activate_variant_id:activateId}:{});
        const done=await hooks.perform('archive','Archivage',async()=>{answer=await hooks.archive(body);return true});
        dlg.busy=false;
        if(!hooks.isCurrent())return;
        if(done&&!done.error){
          hooks.close(false);
          const kept=answer&&answer.active_variant_id||null;
          const n=answer&&answer.count||count;
          /* La sélection ne reste pas sur une variante désormais archivée : le parent de la racine archivée s'il vit, sinon l'active. */
          const parentId=node&&node.parent_variant_id;
          const landing=parentId&&!(answer&&Array.isArray(answer.archived)&&answer.archived.some(r=>r.variant_id===parentId))?parentId:kept;
          await hooks.after(landing,`${n} variante${n>1?'s':''} archivée${n>1?'s':''} (racine #${node?node.variant_number:'?'}). Elles se restaurent depuis « Archivées ».`);
          return;
        }
        /* Refus : la liste a peut-être changé (jeton périmé) -> on recalcule SOUS les yeux de l'utilisateur, il reconfirme. */
        const code=done&&done.error&&done.error.code;
        if(code==='presentation_studio_confirmation_stale'||code==='presentation_studio_stale_revision'){
          const before=model;
          const re=await hooks.perform('plan','Calcul de la liste',async()=>{model=await planFor(activateId);return true});
          if(!hooks.isCurrent())return;
          if(re&&!re.error){
            planAt=now();
            stale=`${describeRefusal({code:'presentation_studio_confirmation_stale'}).text} ${sameSet(before.rows,model.rows)?'La liste est inchangée.':`La liste a changé : ${before.count} → ${model.count}.`}`;
          }else model=before;
        }else if(done&&done.error&&done.error.kind==='refused'){stale=done.error.text}
        paint();dlg.cancel.focus();
      };
      const expired=()=>model.expiresInS!==null&&now()-planAt>model.expiresInS*1000;
      dlg.timer=every(()=>{if(dlg.tick)dlg.tick()},1000);
      paint();
      /* Le choix par défaut est le plus sûr : Annuler. Entrée ne détruit jamais rien. */
      dlg.cancel.focus();
    }

  /* ------------------------------------------------------------------ canal de commandes (long-poll) : la voix ou un agent ouvre l'explorateur */
  function createCommandChannel(deps){
    const stats={polls:0,received:0,answered:0,receiptFailed:0};
    const fetchImpl=deps.fetch;
    const later=deps.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=deps.clearTimeout||((id)=>clearTimeout(id));
    const pageId=deps.pageId||'page'+Math.random().toString(36).slice(2,12).padEnd(8,'0');
    const log=deps.log||(()=>{});
    let visible=true,running=false,failures=0,controller=null;
    const sleep=ms=>new Promise(resolve=>later(resolve,ms));
    async function request(url,options){
      const ctl=typeof AbortController==='function'?new AbortController():null;
      if(options.poll)controller=ctl;
      const timer=later(()=>{if(ctl)ctl.abort()},options.timeoutMs||COMMAND_POLL_TIMEOUT_MS);
      try{
        const init={method:options.method||'GET',cache:'no-store'};
        if(ctl)init.signal=ctl.signal;
        if(options.body){init.body=options.body;init.headers={'Content-Type':'application/json'}}
        const response=await fetchImpl(url,init);
        let body=null;
        try{body=await response.json()}catch(_error){body=null /* intentional: non-JSON answers are reported by their status */}
        return {status:response.status,body};
      }finally{cancelLater(timer);if(controller===ctl)controller=null}
    }
    async function apply(command){
      stats.received+=1;
      let receipt;
      try{receipt=await deps.explorer.handleCommand(command)}
      catch(error){
        log('command_failed',{id:String(command.id).slice(0,8),error:describe(error)},'error');
        receipt={state:'refused',code:'explorer_page_error',reason:describe(error)};
      }
      const body={state:receipt.state};
      for(const key of ['code','mode','fullscreen','presentation_id','variant_id'])if(receipt[key]!==undefined&&receipt[key]!==null)body[key]=receipt[key];
      if(receipt.reason)body.reason=cleanLine(receipt.reason,200);
      try{
        const answer=await request(`${COMMAND_ROUTE}/${encodeURIComponent(command.id)}`,{method:'POST',body:JSON.stringify(body),timeoutMs:4000});
        if(answer.status!==200)throw new Error(`HTTP ${answer.status}`);
        stats.answered+=1;
      }catch(error){stats.receiptFailed+=1;log('receipt_failed',{id:String(command.id).slice(0,8),error:describe(error)},'error')}
    }
    async function once(){
      stats.polls+=1;
      const started=deps.now();
      const answer=await request(`${COMMAND_ROUTE}?wait_s=${COMMAND_POLL_WAIT_S}&page=${pageId}&visible=1`,{poll:true,timeoutMs:COMMAND_POLL_TIMEOUT_MS});
      if(answer.status!==200)throw new Error(`HTTP ${answer.status}`);
      const command=answer.body&&answer.body.command;
      if(command)await apply(command);
      else{const elapsed=deps.now()-started;if(elapsed<COMMAND_MIN_GAP_MS)await sleep(COMMAND_MIN_GAP_MS-elapsed)}
    }
    async function loop(){
      running=true;
      try{
        while(visible){
          try{await once();failures=0}
          catch(error){
            if(!visible)break;
            failures+=1;
            if(failures===1||failures%10===0)log('command_poll_failed',{error:describe(error),failures},'warn');
            await sleep(Math.min(15000,500*Math.pow(2,Math.max(0,failures-1))));
          }
        }
      }finally{running=false}
    }
    function evaluate(){if(!visible||running)return;loop().catch(error=>log('command_loop_failed',{error:describe(error)},'error'))}
    return {
      setVisible(value){
        const next=!!value;if(next===visible)return;visible=next;
        if(!visible){
          if(controller){try{controller.abort()}catch(_error){/* intentional: the poll is dropped either way */}}
          request(`${COMMAND_ROUTE}?wait_s=0&page=${pageId}&visible=0`,{timeoutMs:4000}).catch(error=>log('hidden_notice_failed',{error:describe(error)},'warn'));
        }
        evaluate();
      },
      start(){evaluate()},apply,pageId:()=>pageId,stats:()=>Object.assign({},stats),state:()=>({visible,running,failures}),
    };
  }

  const api=Object.freeze({createTreeView,fillTitleDialog,fillArchiveDialog,createCommandChannel});
  root.JarvisStudioExplorerWidgets=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
