/* Un Core minuscule pour la comparaison et la composition de l'explorateur (studio de présentation, Slice 19, moitié interface).

   S'ajoute à `explorer_world.cjs` : mêmes variantes, mêmes documents, et les routes de `docs/presentation-studio.md` › *Comparison and semantic composition
   contract* avec leurs formes : `GET compare`, `POST compare/{select,pair,mode,navigate,links,links/remove,clear}`, `POST compositions/plan`, `POST compositions`.
   Les règles qui comptent pour l'interface sont tenues : classes d'équivalence de scènes (identifiant commun + liens manuels, transitifs), refus d'un lien
   qui mettrait deux scènes d'une même variante dans une classe (409 `compare_mapping_conflict`), statuts de navigation `origin` / `synced` / `unmapped` / `held`,
   révision attendue (409 `stale_revision`), conflits typés (code, dimension, message, fix) collectés ensemble, plan qui n'écrit rien, création d'un enfant
   à la validation. Ce n'est PAS la preuve de Core (`test_presentation_studio_{compare,compose_service,compose_routes}.py`) : c'est le banc qui lie chaque geste
   de l'interface à une réponse réaliste. */
'use strict';

function installCompare(env, world) {
  const base = '/api/presentation-studio/presentations/' + world.pid;
  const cmp = {state: null, calls: [], planCalls: 0, commitCalls: 0, narrativeUnmapped: false, scoreScenes: {}, failNext: []};
  const json = (status, body) => ({status, body});
  const err = (status, code, message, extra) => json(status, {error: Object.assign({code, message: message || code}, extra || {})});
  const sceneIds = id => { const d = world.doc(id); return d ? d.scenes.map(s => s.scene_id) : []; };
  const sceneOf = (id, sid) => { const d = world.doc(id); return d ? d.scenes.find(s => s.scene_id === sid) : null; };

  function classes(state) {
    const parent = new Map();
    const key = (v, s) => v + '\u0000' + s;
    const find = k => { while (parent.get(k) !== k) { parent.set(k, parent.get(parent.get(k))); k = parent.get(k); } return k; };
    const union = (a, b) => { parent.set(find(a), find(b)); };
    const bySceneId = new Map();
    for (const v of state.ids) for (const s of sceneIds(v)) {
      parent.set(key(v, s), key(v, s));
      if (bySceneId.has(s)) union(key(v, s), bySceneId.get(s)); else bySceneId.set(s, key(v, s));
    }
    const identityRoots = new Map();
    for (const k of parent.keys()) identityRoots.set(k, find(k));
    for (const l of state.links) {
      const a = key(l.a.variant_id, l.a.scene_id), b = key(l.b.variant_id, l.b.scene_id);
      if (parent.has(a) && parent.has(b)) union(a, b);
    }
    return {find, key, parent, identityRoots};
  }
  function conflictInClasses(state) {
    const c = classes(state);
    const seen = new Map();
    for (const k of c.parent.keys()) {
      const root = c.find(k), v = k.split('\u0000')[0];
      const tag = root + '|' + v;
      if (seen.has(tag)) return true;
      seen.set(tag, 1);
    }
    return false;
  }
  function viewOf(state) {
    if (!state || !state.ids.length) return {presentation_id: world.pid, revision: state ? state.revision : 0, active: false, variant_ids: [], layout: 'empty', pair: null, shown: [],
      mode: 'sync', variants: [], structure: {relation: 'identical', pairs: []}, unmapped: {}, links: [], anchors: {}, problems: []};
    const c = classes(state);
    const equivalents = (v, sid) => {
      const out = {};
      const mine = c.find(c.key(v, sid));
      for (const w of state.ids) if (w !== v) {
        const hit = sceneIds(w).find(x => c.find(c.key(w, x)) === mine);
        if (hit) out[w] = hit;
      }
      return out;
    };
    const variants = [], unmapped = {};
    for (const v of state.ids) {
      const node = world.live.find(n => n.variant_id === v);
      if (!node) continue;
      const doc = world.doc(v);
      const scenes = doc.scenes.map((s, index) => {
        const eq = equivalents(v, s.scene_id);
        const identity = Object.keys(eq).some(w => eq[w] === s.scene_id);
        return {scene_id: s.scene_id, index, title: s.title, prefab: s.prefab, mapping: Object.keys(eq).length ? (identity ? 'identity' : 'manual') : 'none', equivalents: eq, suggestions: []};
      });
      unmapped[v] = scenes.filter(s => s.mapping === 'none').map(s => s.scene_id);
      variants.push({variant_id: v, variant_number: node.variant_number, title: node.title, revision: node.revision, active: world.active === v, scene_count: scenes.length, scenes});
    }
    for (const k of Object.keys(unmapped)) if (!unmapped[k].length) delete unmapped[k];
    let relation = 'identical';
    const pairs = [];
    for (let i = 0; i < state.ids.length; i++) for (let j = i + 1; j < state.ids.length; j++) {
      const a = variants.find(x => x.variant_id === state.ids[i]), b = variants.find(x => x.variant_id === state.ids[j]);
      if (!a || !b) continue;
      const ca = a.scenes.map(s => c.find(c.key(a.variant_id, s.scene_id))), cb = b.scenes.map(s => c.find(c.key(b.variant_id, s.scene_id)));
      const sameSet = ca.length === cb.length && ca.every(x => cb.includes(x));
      const rel = sameSet ? (ca.every((x, k) => x === cb[k]) ? 'identical' : 'reordered') : 'divergent';
      pairs.push({a: a.variant_id, b: b.variant_id, relation: rel});
      if (rel === 'divergent' || (rel === 'reordered' && relation === 'identical')) relation = rel;
    }
    const shown = state.pair ? state.pair.slice() : state.ids.slice();
    return {presentation_id: world.pid, revision: state.revision, active: true, variant_ids: state.ids.slice(), layout: state.pair ? 'focus' : (state.ids.length === 4 ? 'four_up' : 'two_up'),
      pair: state.pair, shown, mode: state.mode, variants, structure: {relation, pairs}, unmapped, links: state.links.map(l => ({a: l.a, b: l.b, stale: !!l.stale})),
      anchors: Object.assign({}, state.anchors), problems: state.ids.filter(v => !world.live.some(n => n.variant_id === v)).map(v => ({variant_id: v, code: 'variant_unavailable'}))};
  }
  const bump = state => { state.revision += 1; return state; };
  const stale = (state, body) => body && body.expected_revision !== undefined && state && state.revision !== body.expected_revision
    ? err(409, 'presentation_studio_stale_revision', 'the comparison moved') : null;

  function select(body) {
    const ids = body.variant_ids;
    if (!Array.isArray(ids) || ![2, 4].includes(ids.length) || new Set(ids).size !== ids.length) return err(400, 'presentation_studio_invalid', 'two or four distinct variants');
    for (const v of ids) if (!world.live.some(n => n.variant_id === v)) return err(404, 'presentation_studio_unknown_variant', 'unknown variant');
    const old = cmp.state;
    const bad = stale(old && old.ids.length ? old : null, body); if (bad) return bad;
    const state = {ids: ids.slice(), pair: body.pair || null, mode: body.mode || (old && old.mode) || 'sync', anchors: {}, revision: (old ? old.revision : 0) + 1,
      links: (old ? old.links : []).filter(l => ids.includes(l.a.variant_id) && ids.includes(l.b.variant_id))};
    for (const v of ids) state.anchors[v] = sceneIds(v)[0] || null;
    cmp.state = state;
    return json(200, viewOf(state));
  }
  function navigate(body) {
    const state = cmp.state;
    if (!state || !state.ids.includes(body.variant_id)) return err(404, 'presentation_studio_unknown_variant', 'not compared');
    const list = sceneIds(body.variant_id);
    let target = body.scene_id;
    if (target !== undefined && !list.includes(target)) return err(404, 'presentation_studio_unknown_scene', 'no such scene');
    if (target === undefined) {
      const at = Math.max(0, list.indexOf(state.anchors[body.variant_id]));
      const index = body.step === 'next' ? Math.min(list.length - 1, at + 1) : body.step === 'previous' ? Math.max(0, at - 1) : body.step === 'first' ? 0 : list.length - 1;
      target = list[index];
    }
    state.anchors[body.variant_id] = target;
    const c = classes(state);
    const results = {};
    for (const w of state.ids) if (w !== body.variant_id) {
      if (state.mode === 'independent') { results[w] = {scene_id: state.anchors[w], status: 'held'}; continue; }
      const mine = c.find(c.key(body.variant_id, target));
      const hit = sceneIds(w).find(x => c.find(c.key(w, x)) === mine);
      if (hit) { state.anchors[w] = hit; results[w] = {scene_id: hit, status: 'synced'}; } else results[w] = {scene_id: state.anchors[w], status: 'unmapped'};
    }
    bump(state);
    return json(200, Object.assign(viewOf(state), {navigation: {origin: {variant_id: body.variant_id, scene_id: target}, results}}));
  }
  function links(body, remove) {
    const state = cmp.state;
    if (!state || !state.ids.length) return err(404, 'presentation_studio_unknown_variant', 'no comparison');
    const bad = stale(state, body); if (bad) return bad;
    const {a, b} = body;
    for (const e of [a, b]) {
      if (!e || !state.ids.includes(e.variant_id)) return err(400, 'presentation_studio_invalid', 'compared variants only');
      if (!sceneOf(e.variant_id, e.scene_id)) return err(404, 'presentation_studio_unknown_scene', 'no such scene');
    }
    if (a.variant_id === b.variant_id) return err(400, 'presentation_studio_invalid', 'two different variants');
    const same = (l, x, y) => l.a.variant_id === x.variant_id && l.a.scene_id === x.scene_id && l.b.variant_id === y.variant_id && l.b.scene_id === y.scene_id;
    const [x, y] = [a, b].sort((p, q) => (p.variant_id + p.scene_id) < (q.variant_id + q.scene_id) ? -1 : 1);
    const at = state.links.findIndex(l => same(l, x, y));
    if (remove) {
      if (at < 0) return err(404, 'presentation_studio_unknown_scene', 'no such link');
      state.links.splice(at, 1);
    } else if (at < 0) {
      if (state.links.length >= 64) return err(409, 'presentation_studio_limit_reached', 'too many links');
      state.links.push({a: x, b: y});
      if (conflictInClasses(state)) { state.links.pop(); return err(409, 'presentation_studio_compare_mapping_conflict', 'two scenes of one variant'); }
    }
    bump(state);
    return json(200, viewOf(state));
  }

  function conflictsFor(body) {
    const out = [];
    const scenesFrom = body.scenes || body.base, motionFrom = body.motion || body.base, narrFrom = body.narrative || body.base;
    const have = new Set(sceneIds(scenesFrom));
    const need = cmp.scoreScenes[motionFrom] || sceneIds(motionFrom);
    const missing = need.filter(s => !have.has(s));
    if (missing.length) out.push({code: 'score_scene_missing', dimension: 'motion', message: `Le mouvement cite ${missing.length} scène(s) absente(s) des scènes choisies.`,
      fix: 'Prenez ces scènes de la même variante, ou le mouvement d\'une autre.', details: {scene_ids: missing.slice(0, 12), total: missing.length}});
    if (cmp.narrativeUnmapped && narrFrom !== motionFrom && body.on_unmapped !== 'keep_motion') out.push({code: 'narrative_unmapped_items', dimension: 'narrative',
      message: '2 éléments du mouvement n\'ont pas d\'équivalent dans la narration choisie.', fix: 'Même variante pour les deux, ou « garder la narration d\'origine ».', details: {}});
    return out;
  }
  function compositionOf(body, id) {
    const num = v => (world.live.find(n => n.variant_id === v) || {}).variant_number;
    const names = ['scenes', 'narrative', 'motion', 'art_direction'];
    return {variant_id: id, base_variant_id: body.base, dimensions: names.map(n => ({dimension: n, inherited: !body[n], sources: [{variant_id: body[n] || body.base, variant_number: num(body[n] || body.base)}]})),
      warnings: [], result: {scene_count: sceneIds(body.scenes || body.base).length, has_score: true, has_art_direction: true, item_count: 3, sources: [body.base],
        parent_variant_id: body.base, summary: `composed on #${num(body.base)}; ` + names.filter(n => body[n]).map(n => `${n} #${num(body[n])}`).join('; ') + '.'}};
  }
  function composeCheck(body) {
    const state = cmp.state;
    if (typeof body.title !== 'string' || !body.title.trim()) return err(400, 'presentation_studio_invalid', 'title');
    if (!world.live.some(n => n.variant_id === body.base)) return err(404, 'presentation_studio_unknown_variant', 'unknown base');
    if (body.expected_revision !== undefined && body.expected_revision !== world.revision) return err(409, 'presentation_studio_stale_revision', 'presentation moved');
    for (const [v, rev] of Object.entries(body.source_revisions || {})) {
      const node = world.live.find(n => n.variant_id === v);
      if (!node) return err(404, 'presentation_studio_unknown_variant', 'unknown source');
      if (node.revision !== rev) return err(409, 'presentation_studio_stale_revision', 'a source moved');
    }
    return null;
  }

  env.route(url => url.startsWith(base + '/compare') || url.startsWith(base + '/compositions'), (url, rec, body) => {
    cmp.calls.push({method: rec.method, url: url.slice(base.length), body});
    const i = cmp.failNext.findIndex(f => !f.match || f.match(url, rec));
    if (i >= 0) { const f = cmp.failNext.splice(i, 1)[0]; return json(f.status || 500, f.body || {error: {code: f.code || 'boom', message: 'boom'}}); }
    const tail = url.slice(base.length).split('?')[0];
    if (tail === '/compare' && rec.method === 'GET') return json(200, viewOf(cmp.state && cmp.state.ids.length ? cmp.state : (cmp.state || null)));
    if (tail === '/compare/select') return select(body);
    if (tail === '/compare/pair') { const s = cmp.state; const bad = stale(s, body); if (bad) return bad; s.pair = body.pair || null; bump(s); return json(200, viewOf(s)); }
    if (tail === '/compare/mode') { const s = cmp.state; const bad = stale(s, body); if (bad) return bad; s.mode = body.mode; bump(s); return json(200, viewOf(s)); }
    if (tail === '/compare/navigate') return navigate(body);
    if (tail === '/compare/links') return links(body, false);
    if (tail === '/compare/links/remove') return links(body, true);
    if (tail === '/compare/clear') { const rev = cmp.state ? cmp.state.revision + 1 : 0; cmp.state = {ids: [], pair: null, mode: 'sync', links: [], anchors: {}, revision: rev}; return json(200, {presentation_id: world.pid, cleared: true, active: false, revision: rev}); }
    if (tail === '/compositions/plan') {
      cmp.planCalls += 1;
      const bad = composeCheck(body); if (bad) return bad;
      const conflicts = conflictsFor(body);
      return json(200, {ok: conflicts.length === 0, dry_run: true, conflicts, composition: compositionOf(body, 'psv_' + '9'.repeat(32))});
    }
    if (tail === '/compositions' && rec.method === 'POST') {
      cmp.commitCalls += 1;
      const bad = composeCheck(body); if (bad) return bad;
      const conflicts = conflictsFor(body);
      if (conflicts.length) return err(409, 'presentation_studio_composition_refused', `${conflicts.length} conflict(s)`, {conflicts});
      world.revision += 1;
      const node = world.add(body.base, {title: body.title, rationale: 'composed', created_by: 'user', scene_count: sceneIds(body.scenes || body.base).length});
      if (body.activate) world.active = node.variant_id;
      return json(201, {node: Object.assign({}, node), variant: Object.assign({}, node), presentation_revision: world.revision, activated: !!body.activate, source_variant_id: body.base,
        composition: compositionOf(body, node.variant_id)});
    }
    return err(404, 'no_route', 'unscripted ' + rec.method + ' ' + url);
  });
  return cmp;
}
module.exports = {installCompare};
