/* Composition sémantique de l'explorateur de variantes (handoff jarvis-interactive-presentation-studio, Slice 19, moitié interface).

   Le formulaire « Composer… » et les points d'entrée programmatiques (`plan`, `commit`) qui créent UN NOUVEL ENFANT en empruntant, dimension par dimension
   (scènes, narration, mouvement, direction artistique), à une variante comparée. Les variantes sources ne sont jamais modifiées (Core ne fait que les lire).

   Règles tenues ici :
   - **Plan d'abord, toujours.** Rien n'est créé sans un `POST .../compositions/plan` accepté (`ok: true`) pour EXACTEMENT la demande envoyée ensuite ; le
     bouton « Créer » est inactif tant que le plan affiché n'est pas celui du formulaire courant (signature de la demande). Les conflits sont montrés
     TOUS, avec leur dimension, leur message et leur remède (`fix`) tels que Core les rend, nettoyés (`cleanLine`) et écrits par `textContent`.
   - **Ce que l'utilisateur a comparé est ce qui est composé** : `source_revisions` vient de la vue de comparaison relue à l'ouverture ; une source qui a
     bougé donne `stale_revision` (Core) et la vue est relue.
   - Le relais force l'acteur `user` : ce module n'envoie jamais d'acteur.
   - Après la création, l'arbre relit le graphe de Core et sélectionne l'enfant (`ctx.after`). */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const CC=root.JarvisStudioExplorerCompareCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_compare_core.js'):null);
  const {cleanLine}=Core;
  const PLAN_DEBOUNCE_MS=400;

  function createCompose(ctx){
    const {doc,el,attrs,clear,button,later,cancelLater,log,say,announce}=ctx;
    const planPath=()=>`${ctx.base()}/compositions/plan`;
    const commitPath=()=>`${ctx.base()}/compositions`;

    /* Les conflits portés par une réponse : 200 `{ok:false, conflicts}` pour un plan, 409 `composition_refused` avec `error.conflicts` pour un commit. */
    function conflictsOf(error){
      const info=error&&error.info||error||{};
      return CC.conflictRows(info.conflicts||error&&error.conflicts||[]);
    }
    async function planRequest(request){
      try{
        const answer=await ctx.call('POST',planPath(),request);
        const rows=CC.conflictRows(answer&&answer.conflicts);
        return {ok:answer&&answer.ok===true&&rows.length===0,conflicts:rows,summary:CC.planSummary(answer),answer};
      }catch(error){
        const info=CC.describe(error.info||error,{op:'compose'});
        const rows=conflictsOf(error);
        if(info.code==='presentation_studio_composition_refused'||rows.length)return {ok:false,conflicts:rows,summary:CC.planSummary(null),error:info};
        return {ok:false,conflicts:[],error:info,summary:CC.planSummary(null),status:error.status};
      }
    }
    /* La vue relue juste avant : les révisions comparées sont celles de cet instant. */
    async function freshView(){
      const out=await ctx.refreshView();
      return out&&out.error?null:ctx.getView();
    }
    function requestFrom(form,view){
      return CC.buildRequest(form,view,{expectedRevision:ctx.graphRevision()});
    }

    /* -------------------------------------------------------------- points d'entrée programmatiques (voix / agent) */
    async function plan(raw){
      const view=await freshView();
      if(!view||!view.active)return {error:{text:"Aucune comparaison n'est ouverte.",code:'explorer_page_error'}};
      const built=requestFrom(raw||{},view);
      if(!built.ok)return {error:{text:built.errors.map(e=>e.message).join(' '),code:'presentation_studio_invalid'},conflicts:[]};
      const out=await planRequest(built.request);
      log('compose_planned',{ok:out.ok,conflicts:out.conflicts.length});
      if(out.error&&!out.conflicts.length)return {error:out.error,conflicts:[]};
      return {ok:out.ok,conflicts:out.conflicts,summary:out.summary,request_signature:built.signature};
    }
    /* Créer = plan accepté, puis création. Rien n'est jamais créé sans plan. */
    async function commit(raw){
      const view=await freshView();
      if(!view||!view.active)return {error:{text:"Aucune comparaison n'est ouverte.",code:'explorer_page_error'}};
      const built=requestFrom(raw||{},view);
      if(!built.ok)return {error:{text:built.errors.map(e=>e.message).join(' '),code:'presentation_studio_invalid'},conflicts:[]};
      const checked=await planRequest(built.request);
      if(!checked.ok)return checked.error&&!checked.conflicts.length?{error:checked.error,conflicts:[]}:{ok:false,conflicts:checked.conflicts,summary:checked.summary};
      return create(built.request,checked.summary);
    }
    async function create(request,summary,beforeAfter){
      try{
        const answer=await ctx.call('POST',commitPath(),request);
        const node=answer&&(answer.node||answer.variant)||{};
        const id=node.variant_id||answer&&answer.variant&&answer.variant.variant_id||null;
        const number=node.variant_number||answer&&answer.variant&&answer.variant.variant_number||'?';
        const text=`Variante #${number} composée${answer&&answer.composition&&answer.composition.result&&answer.composition.result.summary?' ('+cleanLine(answer.composition.result.summary,120)+')':''}. Les sources n'ont pas bougé.`;
        log('compose_created',{variant_id:id});
        if(typeof beforeAfter==='function')beforeAfter();
        await ctx.after(id,text);
        return {ok:true,created:true,variant_id:id,variant_number:node.variant_number||null,summary:CC.planSummary(answer),message:text};
      }catch(error){
        const info=CC.describe(error.info||error,{op:'compose'});
        const rows=conflictsOf(error);
        log('compose_failed',{code:info.code,conflicts:rows.length},info.kind==='failed'?'error':'warn');
        if(info.kind==='stale'){say('stale',info.text);ctx.refreshView()}
        return {ok:false,created:false,error:info,conflicts:rows,summary};
      }
    }

    /* -------------------------------------------------------------- le formulaire */
    function openDialog(options){
      const opts=options||{};
      const view=ctx.getView();
      if(!view||!view.active)return null;
      const dlg=ctx.dialog.open({kind:'compose',titleId:'jvxDialogTitle',returnFocus:opts.returnFocus});
      const ids=view.variant_ids;
      const form=Object.assign(CC.emptyForm(view,opts.base),opts.preset||{});
      if(!form.title)form.title=CC.suggestTitle(view,form);
      const P={status:'idle',signature:'',conflicts:[],summary:null,error:'',busy:false,timer:null};
      const box=dlg.box;
      const heading=el('h2','','Composer une nouvelle variante');heading.id='jvxDialogTitle';
      box.appendChild(heading);
      box.appendChild(el('p','',"Choisissez, pour chaque dimension, la variante dont elle vient. Le résultat est une NOUVELLE variante enfant de la variante de départ ; les sources restent intactes. Rien n'est créé avant une vérification sans conflit."));
      const formEl=el('form');
      formEl.addEventListener('submit',event=>{event.preventDefault();submit()});
      const field=(label,control,id,hint)=>{
        const f=el('div','jvx-field');
        const l=el('label','',label);l.setAttribute('for',id);control.id=id;
        f.appendChild(l);f.appendChild(control);
        if(hint){const h=el('div','jvx-hint',hint);h.id=id+'Hint';control.setAttribute('aria-describedby',h.id);f.appendChild(h)}
        formEl.appendChild(f);
        return f;
      };
      const option=(select,value,text)=>{const o=el('option','',text);o.value=value;select.appendChild(o)};
      const variantText=id=>{const v=CC.variantOf(view,id);return v?`#${v.variant_number} ${cleanLine(v.title,50)||'(sans titre)'}`:id};
      const title=el('input');attrs(title,{type:'text',maxlength:'400',autocomplete:'off',spellcheck:'false'});title.value=form.title;
      field('Titre de la nouvelle variante',title,'jvxCmpTitle');
      const baseSel=el('select');
      ids.forEach(id=>option(baseSel,id,variantText(id)));baseSel.value=form.base;
      field('Variante de départ (parent)',baseSel,'jvxCmpBase',"L'enfant est une branche de cette variante ; tout ce que vous ne choisissez pas ci-dessous vient d'elle.");
      const dimSel={};
      for(const dim of CC.DIMENSIONS){
        const sel=el('select');
        option(sel,'','Comme la variante de départ');
        ids.forEach(id=>option(sel,id,variantText(id)));
        sel.value=form[dim.key]||'';
        dimSel[dim.key]=sel;
        field(dim.label,sel,'jvxCmp_'+dim.key,dim.hint);
      }
      const why=el('textarea');attrs(why,{maxlength:'800'});why.value=form.rationale;
      field(`Pourquoi cette composition ? (facultatif, ${CC.MAX_RATIONALE} caractères)`,why,'jvxCmpWhy');
      const unm=el('select');
      option(unm,'refuse','Refuser (je choisis la même variante pour les deux)');
      option(unm,'keep_motion',"Garder la narration d'origine du mouvement");
      unm.value=form.on_unmapped;
      field("Éléments du mouvement sans équivalent dans la narration choisie",unm,'jvxCmpUnm');
      const activeLabel=el('label','jvx-check');
      const activeBox=el('input');activeBox.type='checkbox';activeBox.checked=!!form.activate;
      activeLabel.appendChild(activeBox);activeLabel.appendChild(el('span','','Activer la nouvelle variante tout de suite'));
      formEl.appendChild(activeLabel);
      /* La zone de verdict : lue à voix haute, remplacée à chaque plan. */
      const verdict=el('div','jvx-cmp-verdict');attrs(verdict,{role:'status','aria-live':'polite'});
      formEl.appendChild(verdict);
      const actions=el('div','jvx-dialog-actions');
      const cancel=button('Annuler','jvx-btn',()=>ctx.dialog.cancel());
      const check=button('Vérifier','jvx-btn',()=>{runPlan()});
      const create_=button('Créer la variante','jvx-btn',null);
      create_.setAttribute('data-primary','');create_.setAttribute('type','submit');
      for(const n of [cancel,check,create_])actions.appendChild(n);
      formEl.appendChild(actions);
      box.appendChild(formEl);

      function readForm(){
        form.title=title.value;form.base=baseSel.value;
        for(const dim of CC.DIMENSIONS)form[dim.key]=dimSel[dim.key].value;
        form.rationale=why.value;form.on_unmapped=unm.value;form.activate=activeBox.checked;
      }
      function current(){readForm();return requestFrom(form,ctx.getView()||view)}
      function paintVerdict(){
        clear(verdict);
        const built=current();
        const same=P.signature===built.signature;
        if(P.busy){verdict.appendChild(el('p','','Vérification en cours…'))}
        else if(!built.ok){
          const ul=el('ul','jvx-conflicts');
          built.errors.forEach(e=>ul.appendChild(el('li','',e.message)));
          verdict.appendChild(ul);
        }else if(P.status==='ok'&&same){
          const ok=el('div','jvx-plan-ok','Aucun conflit : la composition peut être créée.');verdict.appendChild(ok);
          if(P.summary){
            const lines=P.summary.lines.slice();
            if(lines.length)verdict.appendChild(el('p','',`Résultat : ${lines.join(', ')}.`));
            const ul=el('ul','jvx-set');ul.setAttribute('aria-label','Provenance des dimensions');
            P.summary.provenance.forEach(p=>ul.appendChild(el('li','',`${p.label} : ${p.inherited?'héritée de ':'prise de '}${p.from.map(n=>'#'+n).join(', ')||'la variante de départ'}`)));
            verdict.appendChild(ul);
            P.summary.warnings.forEach(w=>verdict.appendChild(el('div','jvx-warnbox',w)));
          }
        }else if((P.status==='refused')&&same){
          verdict.appendChild(el('p','',`${P.conflicts.length} conflit${P.conflicts.length>1?'s':''} : rien n'a été créé. Appliquez chaque remède, puis vérifiez de nouveau.`));
          const ul=el('ul','jvx-conflicts');
          P.conflicts.forEach(c=>{
            const li=el('li');
            li.setAttribute('data-code',c.code);
            li.appendChild(el('strong','',`${c.dimensionLabel} — `));
            li.appendChild(el('span','jvx-bidi',c.message));
            li.appendChild(el('span','jvx-fix',`À faire : ${c.fix||'voir le message'}`));
            ul.appendChild(li);
          });
          verdict.appendChild(ul);
        }else if(P.status==='error'&&same){
          verdict.appendChild(el('div','jvx-warnbox',P.error));
        }else{
          verdict.appendChild(el('p','',P.status==='idle'?'Pas encore vérifiée.':'Le formulaire a changé : la vérification doit être refaite.'));
        }
        create_.setAttribute('aria-disabled',built.ok&&P.status==='ok'&&same&&!P.busy?'false':'true');
        create_.title=create_.getAttribute('aria-disabled')==='true'?'Une vérification sans conflit est nécessaire avant de créer.':'Créer la nouvelle variante';
      }
      async function runPlan(){
        if(P.busy)return;
        const built=current();
        if(!built.ok){paintVerdict();return}
        if(P.timer){cancelLater(P.timer);P.timer=null}
        P.busy=true;paintVerdict();
        /* Les révisions comparées sont relues à l'instant de la vérification. */
        const fresh=await freshView();
        const again=fresh?requestFrom(form,fresh):built;
        const out=await planRequest(again.request);
        P.busy=false;
        if(ctx.dialog.current()!==dlg)return;
        P.signature=again.signature;
        if(out.ok){P.status='ok';P.conflicts=[];P.summary=out.summary}
        else if(out.conflicts.length){P.status='refused';P.conflicts=out.conflicts;P.summary=null;announce(`${out.conflicts.length} conflit${out.conflicts.length>1?'s':''} de composition.`)}
        else{P.status='error';P.error=out.error&&out.error.text||'Core a refusé cette composition.';if(out.error&&out.error.kind==='stale'){}}
        paintVerdict();
        if(P.status==='ok')announce('Aucun conflit.');
      }
      async function submit(){
        if(P.busy)return;
        const built=current();
        if(!built.ok){paintVerdict();(formEl.querySelector('input'))&&title.focus();return}
        if(!(P.status==='ok'&&P.signature===built.signature)){await runPlan();return}
        P.busy=true;paintVerdict();
        const out=await create(built.request,P.summary,()=>{if(ctx.dialog.current()===dlg)ctx.dialog.close(false)});
        P.busy=false;
        if(out.ok)return;
        if(ctx.dialog.current()!==dlg)return;
        /* Refus au commit (état changé depuis le plan) : les conflits sont montrés, le plan est invalidé. */
        P.signature=built.signature;
        if(out.conflicts&&out.conflicts.length){P.status='refused';P.conflicts=out.conflicts}
        else{P.status='error';P.error=out.error&&out.error.text||'Core a refusé cette composition.'}
        paintVerdict();
      }
      const onChange=()=>{
        if(P.timer)cancelLater(P.timer);
        paintVerdict();
        P.timer=later(()=>{P.timer=null;if(ctx.dialog.current()===dlg)runPlan()},PLAN_DEBOUNCE_MS);
      };
      for(const control of [title,baseSel,unm,why,activeBox,...Object.values(dimSel)]){
        control.addEventListener(control===title||control===why?'input':'change',onChange);
      }
      paintVerdict();
      title.focus();title.select();
      /* Un premier plan tout de suite : l'utilisateur voit les conflits de la configuration de départ sans rien demander. */
      P.timer=later(()=>{P.timer=null;if(ctx.dialog.current()===dlg)runPlan()},PLAN_DEBOUNCE_MS);
      return dlg;
    }

    return {plan,commit,openDialog};
  }

  const api=Object.freeze({createCompose,PLAN_DEBOUNCE_MS});
  root.JarvisStudioExplorerCompose=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
