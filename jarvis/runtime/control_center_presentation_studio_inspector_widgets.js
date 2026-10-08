/* Inspecteur d'édition du Studio, partie 2/3 : les widgets GÉNÉRÉS (handoff jarvis-interactive-presentation-studio, Slice 07).
   Exposé en `window.JarvisStudioInspectorWidgets` et en `module.exports`. `createWidgets(kit)` rend `makeWidget(ctx, slot, inputId, handlers)` : un
   widget par type de ligne d'introspection (`widgetSpec`), jamais par identifiant de réglage. Un widget ne parle que par trois gestes,
   `handlers.preview` (aperçu), `handlers.idle` (pas : UN enregistrement après une pause) et `handlers.commit` (valeur finale : sortie du champ, Entrée,
   relâchement, clic) ; il ne connaît ni Core, ni la file, ni l'historique. `kit` : `{doc, el, attrs, button, clear, sessionFor, setRowMessage, log}`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioInspectorCore||(typeof require==='function'?require('./control_center_presentation_studio_inspector_core.js'):null);
  const {HEX_COLOR,describe,clip,sameJson,widgetSpec,roundTo}=Core;

  function createWidgets(kit){
    const {doc,el,attrs,button,clear,sessionFor,setRowMessage,log}=kit;

    function makeWidget(ctx,slot,inputId,h){
      const row=ctx.row,spec=widgetSpec(row);
      const id=row.control_id;
      const preview=(value,opts)=>h.preview(ctx,value,opts);
      const commit=(value,opts)=>h.commit(ctx,value,opts);
      const idle=(value)=>h.idle(ctx,value);
      switch(spec.kind){
        case 'slider':case 'number':return numberWidget(ctx,slot,inputId,spec,{preview,commit,idle});
        case 'toggle':return toggleWidget(ctx,slot,inputId,{commit,idle});
        case 'color':return colorWidget(ctx,slot,inputId,{preview,commit,idle});
        case 'segmented':return segmentedWidget(ctx,slot,inputId,spec,{commit,idle});
        case 'select':return selectWidget(ctx,slot,inputId,spec,{commit,idle});
        case 'text':case 'url':return textWidget(ctx,slot,inputId,spec,{preview,commit,idle},false);
        case 'textarea':return textWidget(ctx,slot,inputId,spec,{preview,commit,idle},true);
        case 'stops':return stopsWidget(ctx,slot,inputId,spec,{preview,commit,idle});
        case 'json':return jsonWidget(ctx,slot,inputId,spec,{preview,commit,idle});
        default:{
          const pre=el('pre','jvi-readonly');pre.id=inputId;slot.appendChild(pre);
          log('widget_readonly',{control_id:id,type:row.type});
          return {input:null,set(v){pre.textContent=JSON.stringify(v,null,2)},refresh(){},focus(){pre.setAttribute('tabindex','0');pre.focus()}};
        }
      }
    }

    function numberWidget(ctx,slot,inputId,spec,ev){
      const isRange=spec.kind==='slider';
      let range=null;
      const num=el('input','jvi-num');num.type='number';num.id=inputId;num.step=String(spec.integer?1:'any');
      num.setAttribute('inputmode',spec.integer?'numeric':'decimal');
      if(spec.min!==null)num.min=String(spec.min);
      if(spec.max!==null)num.max=String(spec.max);
      const minus=button('−','jvi-step',null,{'aria-label':`Diminuer ${ctx.row.label}`,tabindex:-1});
      const plus=button('+','jvi-step',null,{'aria-label':`Augmenter ${ctx.row.label}`,tabindex:-1});
      if(isRange){
        range=el('input','jvi-range');range.type='range';
        range.min=String(spec.min);range.max=String(spec.max);range.step=String(spec.step);
        range.setAttribute('aria-label',`${ctx.row.label} (curseur)`);
        slot.appendChild(range);
      }
      slot.appendChild(minus);slot.appendChild(num);slot.appendChild(plus);
      const pct=(v)=>{if(!range)return;const p=spec.max>spec.min?Math.max(0,Math.min(100,(v-spec.min)/(spec.max-spec.min)*100)):0;range.style.setProperty('--pct',p+'%')};
      const parse=(text)=>{const t=String(text).trim().replace(',','.');return t===''?NaN:Number(t)};
      const session=()=>sessionFor(ctx);
      const show=(v)=>{
        if(typeof v==='number'&&Number.isFinite(v)){
          if(String(num.value)!==String(v))num.value=String(v);
          if(range){range.value=String(v);pct(v)}
        }
      };
      const nudge=(dir)=>{
        const cur=parse(num.value);
        const from=Number.isFinite(cur)?cur:(typeof ctx.row.current==='number'?ctx.row.current:0);
        let next=roundTo(from+dir*spec.step,spec.step);
        if(spec.min!==null)next=Math.max(spec.min,next);
        if(spec.max!==null)next=Math.min(spec.max,next);
        show(next);ev.idle(next);
      };
      minus.addEventListener('click',()=>nudge(-1));
      plus.addEventListener('click',()=>nudge(1));
      if(range){
        const release=()=>{const s=session();if(s.pointer){s.pointer=false;ev.commit(Number(range.value),{immediate:true})}};
        range.addEventListener('pointerdown',()=>{session().pointer=true;
          const done=()=>{doc.removeEventListener('pointerup',done,true);doc.removeEventListener('pointercancel',done,true);release()};
          doc.addEventListener('pointerup',done,true);doc.addEventListener('pointercancel',done,true)});
        range.addEventListener('input',()=>{
          const v=spec.integer?Math.round(Number(range.value)):roundTo(Number(range.value),spec.step);
          num.value=String(v);pct(v);
          if(session().pointer)ev.preview(v);else ev.idle(v);
        });
        range.addEventListener('change',()=>{if(session().pointer){session().pointer=false;ev.commit(Number(range.value),{immediate:true})}});
        range.addEventListener('blur',()=>{if(session().dirty)ev.commit(Number(range.value),{immediate:true})});
        range.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();ev.commit(Number(range.value),{immediate:true})}});
      }
      /* `input` (frappe, flèches, molette, ressort du champ) et `change` (Chrome en émet un à CHAQUE pas de flèche ou de molette) vont par
         le même chemin que le clavier du curseur : aperçu, puis UN enregistrement après une pause, à la sortie du champ ou sur Entrée. */
      num.addEventListener('input',()=>{
        const v=parse(num.value);
        if(Number.isNaN(v)){setRowMessage(ctx.row.control_id,'bad','Saisissez un nombre.');return}
        if(range)range.value=String(v),pct(v);
        ev.idle(v);
      });
      num.addEventListener('change',()=>{const v=parse(num.value);if(Number.isNaN(v))return;ev.idle(v)});
      num.addEventListener('blur',()=>{if(session().dirty){const v=parse(num.value);if(!Number.isNaN(v))ev.commit(v,{immediate:true})}});
      num.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();const v=parse(num.value);if(!Number.isNaN(v))ev.commit(v,{immediate:true})}});
      return {input:range||num,set:show,refresh(row){
        const v=typeof row.current==='number'?row.current:null;
        minus.disabled=plus.disabled=false;
        if(v!==null&&spec.min!==null)minus.disabled=v<=spec.min;
        if(v!==null&&spec.max!==null)plus.disabled=v>=spec.max;
        if(range)range.setAttribute('aria-valuetext',String(num.value));
      },focus(){(range||num).focus()}};
    }

    function toggleWidget(ctx,slot,inputId,ev){
      const sw=el('button','jvi-switch');sw.type='button';sw.id=inputId;
      attrs(sw,{role:'switch','aria-checked':'false'});
      sw.setAttribute('aria-label',ctx.row.label||ctx.row.control_id);
      const txt=el('span',null,'');
      slot.appendChild(sw);slot.appendChild(txt);
      const show=(v)=>{sw.setAttribute('aria-checked',String(v===true));txt.textContent=v===true?'activé':'désactivé'};
      sw.addEventListener('click',()=>{const next=sw.getAttribute('aria-checked')!=='true';show(next);ev.commit(next,{immediate:true})});
      return {input:sw,set:show,refresh(){},focus(){sw.focus()}};
    }

    function colorWidget(ctx,slot,inputId,ev){
      const pick=el('input','jvi-swatchbtn');pick.type='color';
      pick.setAttribute('aria-label',`${ctx.row.label} (sélecteur de couleur)`);
      const hex=el('input','jvi-hex');hex.type='text';hex.id=inputId;hex.maxLength=7;hex.setAttribute('spellcheck','false');
      hex.setAttribute('autocomplete','off');hex.setAttribute('aria-label',`${ctx.row.label} (valeur hexadécimale)`);
      slot.appendChild(pick);slot.appendChild(hex);
      const session=()=>sessionFor(ctx);
      const show=(v)=>{if(typeof v==='string'&&HEX_COLOR.test(v)){pick.value=v.toLowerCase();hex.value=v.toLowerCase()}};
      pick.addEventListener('input',()=>{hex.value=pick.value;session().pointer=true;ev.preview(pick.value)});
      pick.addEventListener('change',()=>{session().pointer=false;ev.idle(pick.value)});
      pick.addEventListener('blur',()=>{if(session().dirty)ev.commit(pick.value,{immediate:true})});
      hex.addEventListener('input',()=>{
        const t=hex.value.trim();
        if(HEX_COLOR.test(t)){pick.value=t.toLowerCase();ev.preview(t.toLowerCase())}
        else setRowMessage(ctx.row.control_id,'bad','Couleur attendue au format #rrggbb.');
      });
      const finish=()=>{const t=hex.value.trim();if(HEX_COLOR.test(t))ev.commit(t.toLowerCase(),{immediate:true});else if(session().dirty||t!==ctx.row.current)setRowMessage(ctx.row.control_id,'bad','Couleur attendue au format #rrggbb. Rien n\'a été enregistré.')};
      hex.addEventListener('change',finish);
      hex.addEventListener('blur',()=>{if(session().dirty)finish()});
      hex.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();finish()}});
      return {input:hex,set:show,refresh(){},focus(){hex.focus()}};
    }

    function segmentedWidget(ctx,slot,inputId,spec,ev){
      const group=el('div','jvi-seg');group.id=inputId;
      attrs(group,{role:'radiogroup','aria-label':ctx.row.label||ctx.row.control_id});
      const buttons=spec.choices.map((choice)=>{
        const b=button(String(choice),null,null,{role:'radio','aria-checked':'false',tabindex:-1});
        b.setAttribute('data-value',String(choice));
        group.appendChild(b);return b;
      });
      slot.appendChild(group);
      const show=(v)=>{
        buttons.forEach((b,i)=>{const on=spec.choices[i]===v;b.setAttribute('aria-checked',String(on))});
        const tabbable=buttons.findIndex((b,i)=>spec.choices[i]===v);
        buttons.forEach((b,i)=>b.setAttribute('tabindex',String(i===(tabbable<0?0:tabbable)?0:-1)));
      };
      /* Un clic est un choix (enregistré tout de suite) ; parcourir au clavier est un pas : un seul enregistrement après une pause. */
      const choose=(i,stepping)=>{show(spec.choices[i]);buttons[i].focus();if(stepping)ev.idle(spec.choices[i]);else ev.commit(spec.choices[i],{immediate:true})};
      const chosen=()=>{const i=buttons.findIndex((b)=>b.getAttribute('aria-checked')==='true');return i<0?null:spec.choices[i]};
      buttons.forEach((b,i)=>{
        b.addEventListener('click',()=>choose(i,false));
        b.addEventListener('keydown',(event)=>{
          const move={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key];
          if(move){event.preventDefault();choose((i+move+buttons.length)%buttons.length,true)}
          else if(event.key==='Home'){event.preventDefault();choose(0,true)}
          else if(event.key==='End'){event.preventDefault();choose(buttons.length-1,true)}
          else if(event.key==='Enter'){event.preventDefault();ev.commit(chosen(),{immediate:true})}
        });
        b.addEventListener('blur',()=>{if(sessionFor(ctx).dirty&&chosen()!==null&&!group.contains(doc.activeElement))ev.commit(chosen(),{immediate:true})});
      });
      return {input:null,set:show,refresh(){},focus(){const t=buttons.find((b)=>b.getAttribute('tabindex')==='0')||buttons[0];if(t)t.focus()}};
    }

    function selectWidget(ctx,slot,inputId,spec,ev){
      const select=el('select');select.id=inputId;
      for(const choice of spec.choices){const o=el('option',null,String(choice));o.value=String(choice);select.appendChild(o)}
      slot.appendChild(select);
      const current=()=>spec.choices.find((c)=>String(c)===select.value);
      /* `change` part à chaque flèche d'une liste fermée : même chemin que les autres pas (un enregistrement après une pause). */
      select.addEventListener('change',()=>{const v=current();if(v!==undefined)ev.idle(v)});
      select.addEventListener('blur',()=>{const v=current();if(sessionFor(ctx).dirty&&v!==undefined)ev.commit(v,{immediate:true})});
      select.addEventListener('keydown',(event)=>{if(event.key==='Enter'){const v=current();if(v!==undefined)ev.commit(v,{immediate:true})}});
      return {input:select,set(v){select.value=String(v)},refresh(){},focus(){select.focus()}};
    }

    function textWidget(ctx,slot,inputId,spec,ev,multi){
      const field=multi?el('textarea'):el('input');
      if(!multi)field.type=spec.kind==='url'?'url':'text';
      field.id=inputId;
      if(spec.maxLength)field.maxLength=spec.maxLength*2;     /* le compteur et la validation disent la limite exacte */
      field.setAttribute('autocomplete','off');
      if(spec.kind==='url'||!multi)field.setAttribute('spellcheck','false');
      const wrap=el('div');wrap.style.flex='1 1 auto';wrap.style.minWidth='0';wrap.appendChild(field);
      const count=el('div','jvi-count');count.hidden=!spec.maxLength;
      wrap.appendChild(count);slot.appendChild(wrap);
      const session=()=>sessionFor(ctx);
      const upd=()=>{if(spec.maxLength)count.textContent=`${field.value.length} / ${spec.maxLength}`};
      field.addEventListener('input',()=>{upd();ev.preview(field.value,{text:true})});
      const finish=()=>{if(session().dirty||field.value!==String(ctx.row.current===null||ctx.row.current===undefined?'':ctx.row.current))ev.commit(field.value,{immediate:true})};
      field.addEventListener('change',finish);
      field.addEventListener('blur',()=>{if(session().dirty)finish()});
      field.addEventListener('keydown',(event)=>{
        if(event.key==='Enter'&&(!multi||event.ctrlKey||event.metaKey)){event.preventDefault();ev.commit(field.value,{immediate:true})}
      });
      return {input:field,set(v){const t=v===null||v===undefined?'':String(v);if(field.value!==t)field.value=t;upd()},refresh(){},focus(){field.focus()}};
    }

    function stopsWidget(ctx,slot,inputId,spec,ev){
      const wrap=el('div');wrap.style.flex='1 1 auto';wrap.style.minWidth='0';wrap.id=inputId;
      wrap.setAttribute('tabindex','-1');
      const bar=el('div','jvi-grad');bar.setAttribute('aria-hidden','true');
      const list=el('ul','jvi-stops');
      const add=button('Ajouter une étape','jvi-btn',null);
      wrap.appendChild(bar);wrap.appendChild(list);wrap.appendChild(add);slot.appendChild(wrap);
      let stops=[];
      const paintBar=()=>{bar.style.background=stops.length>1?`linear-gradient(90deg,${stops.join(',')})`:(stops[0]||'transparent')};
      const publish=(final)=>{paintBar();const copy=stops.slice();if(final==='idle')ev.idle(copy);else if(final)ev.commit(copy,{immediate:true});else ev.preview(copy)};
      const rebuild=()=>{
        clear(list);
        stops.forEach((color,i)=>{
          const li=el('li','jvi-stop');
          const pick=el('input','jvi-swatchbtn');pick.type='color';pick.value=color;pick.setAttribute('aria-label',`${ctx.row.label} : étape ${i+1} sur ${stops.length}`);
          const hex=el('input','jvi-hex');hex.type='text';hex.value=color;hex.maxLength=7;hex.setAttribute('aria-label',`${ctx.row.label} : étape ${i+1}, valeur hexadécimale`);
          pick.addEventListener('input',()=>{stops[i]=pick.value;hex.value=pick.value;publish(false)});
          pick.addEventListener('change',()=>{stops[i]=pick.value;publish('idle')});
          pick.addEventListener('blur',()=>{if(sessionFor(ctx).dirty){stops[i]=pick.value;publish(true)}});
          const fin=()=>{const t=hex.value.trim();if(HEX_COLOR.test(t)){stops[i]=t.toLowerCase();pick.value=stops[i];publish(true)}else setRowMessage(ctx.row.control_id,'bad','Couleur attendue au format #rrggbb. Rien n\'a été enregistré.')};
          hex.addEventListener('change',fin);
          hex.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();fin()}});
          const up=button('↑','jvi-step',()=>{if(i>0){[stops[i-1],stops[i]]=[stops[i],stops[i-1]];rebuild();publish(true)}},{'aria-label':`Monter l'étape ${i+1}`});
          const down=button('↓','jvi-step',()=>{if(i<stops.length-1){[stops[i+1],stops[i]]=[stops[i],stops[i+1]];rebuild();publish(true)}},{'aria-label':`Descendre l'étape ${i+1}`});
          const del=button('×','jvi-step',()=>{stops.splice(i,1);rebuild();publish(true)},{'aria-label':`Retirer l'étape ${i+1}`});
          up.disabled=i===0;down.disabled=i===stops.length-1;del.disabled=stops.length<=1;
          [pick,hex,up,down,del].forEach((n)=>li.appendChild(n));list.appendChild(li);
        });
        add.disabled=spec.maxItems!==null&&stops.length>=spec.maxItems;
      };
      add.addEventListener('click',()=>{stops.push(stops[stops.length-1]||'#ffffff');rebuild();publish(true)});
      return {input:wrap,set(v){if(Array.isArray(v)&&v.every((c)=>typeof c==='string'&&HEX_COLOR.test(c))){const next=v.map((c)=>c.toLowerCase());if(sameJson(next,stops)&&list.firstChild)return;stops=next;rebuild();paintBar()}},
        refresh(){},focus(){const first=list.querySelector('input');if(first)first.focus()}};
    }

    function jsonWidget(ctx,slot,inputId,spec,ev){
      const area=el('textarea','jvi-json');area.id=inputId;area.setAttribute('spellcheck','false');
      const wrap=el('div');wrap.style.flex='1 1 auto';wrap.style.minWidth='0';wrap.appendChild(area);
      const note=el('div','jvi-count',`JSON : un tableau${spec.maxItems?`, au plus ${spec.maxItems} éléments`:''}. Vérifié avant envoi, puis par Core.`);
      note.style.textAlign='left';wrap.appendChild(note);slot.appendChild(wrap);
      const session=()=>sessionFor(ctx);
      const parse=()=>{try{return {ok:true,value:JSON.parse(area.value)}}catch(error){return {ok:false,error:describe(error)}}};
      area.addEventListener('input',()=>{
        const p=parse();
        if(!p.ok){setRowMessage(ctx.row.control_id,'bad',`JSON invalide : ${clip(p.error,120)}. Rien n'est envoyé.`);return}
        ev.preview(p.value);
      });
      const finish=()=>{
        const p=parse();
        if(!p.ok){setRowMessage(ctx.row.control_id,'bad',`JSON invalide : ${clip(p.error,120)}. Rien n'a été enregistré.`);return}
        ev.commit(p.value,{immediate:true});
      };
      area.addEventListener('change',finish);
      area.addEventListener('blur',()=>{if(session().dirty)finish()});
      area.addEventListener('keydown',(event)=>{
        if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();finish()}
      });
      return {input:area,set(v){const t=JSON.stringify(v===undefined?null:v,null,2);const p=parse();if(p.ok&&sameJson(p.value,v)&&area.value!=='')return;area.value=t},refresh(){},focus(){area.focus()}};
    }


    return {makeWidget};
  }

  const api={createWidgets};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.JarvisStudioInspectorWidgets=api;
})(typeof globalThis!=='undefined'?globalThis:this);
