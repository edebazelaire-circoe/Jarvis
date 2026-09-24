"""Client pur de la scène (handoff jarvis-constellation-scene-runtime, Slice 03).

Ce qui doit tenir, prouvé en exécutant `control_center_scene.js` avec node —
le fichier même que `ControlCenter.index` insère dans la page :

- **parité** : des commandes aléatoires passées au vrai réducteur Python
  (`apply_scene_command`), puis leurs patchs appliqués par le client JS depuis
  l'instantané initial, donnent exactement l'instantané Python final (ordre
  des objets, relations, pierres tombales et leur éviction à 4 096 compris) ;
- **convergence** : avec pertes de réponses, patchs en double, réponses
  bornées, anneau dépassé et redémarrage de Core (autre époque), le client
  finit égal à l'instantané du serveur ;
- chaque motif de resynchronisation est signalé (saut, autre scène, autre
  époque, `resync_required`, patch refusé), et un patch refusé ne laisse
  rien de moitié appliqué.
"""

from __future__ import annotations

import random

import pytest

from jarvis.domain.scene import (
    MAX_ARCHIVED_IDS,
    ExecState,
    RelationKind,
    Representation,
    SceneActor,
    SceneCommand,
    SceneCommandOutcome,
    SceneGeometry,
    SceneObjectFields,
    SceneObjectKind,
    SceneOp,
    ScenePayload,
    ScenePayloadItem,
    SceneRelation,
    SceneSnapshot,
    Visibility,
    apply_scene_command,
)
from jarvis.domain.scene_batch import SceneDelta, SelectionChanges
from jarvis.domain.scene_selection import SceneSelection
from jarvis.runtime.control_center import SCENE_SCRIPT_MARKER, ControlCenter
from tests.conftest import CONTROL_CENTER_SCENE_JS

TITLES = ("Analyse du dépôt", "Résumé 🚀", 'Guillemets "et" \\ barres', "Titre — tiret long", "東京の調査")


def random_command(rng: random.Random, step: int) -> SceneCommand:
    """Une commande plausible ou non : les refus du domaine font partie du parcours."""

    stars = [f"star-{index}" for index in range(8)]
    notes = [f"note-{index}" for index in range(24)]
    actor = rng.choice((SceneActor.BRAIN, SceneActor.USER))
    roll = rng.random()
    if roll < 0.18:
        return SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=SceneActor.RUNTIME, object_id=rng.choice(stars),
            fields=SceneObjectFields(kind=SceneObjectKind.AGENT, category="agent",
                                     exec_state=rng.choice((ExecState.RUNNING, ExecState.COMPLETED, ExecState.FAILED))),
        )
    if roll < 0.40:
        return SceneCommand(
            op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=f"{rng.choice(notes)}-{step // 40}",
            fields=SceneObjectFields(
                kind=rng.choice((SceneObjectKind.ARTIFACT, SceneObjectKind.WINDOW, SceneObjectKind.GROUP)),
                category=rng.choice(("research", "error", "castor")),
                payload=ScenePayload(title=rng.choice(TITLES), summary="ligne 1\nligne 2",
                                     items=(ScenePayloadItem(label="doc", url="https://example.org/a?b=é"),)),
                layer=rng.choice((None, 50, 120, 150)),
            ),
        )
    target = f"{rng.choice(notes)}-{rng.randrange(max(1, step // 40 + 1))}"
    if roll < 0.52:
        return SceneCommand(op=SceneOp.SET_GEOMETRY, actor=actor, object_id=rng.choice((target, rng.choice(stars))),
                            geometry=SceneGeometry(x=rng.uniform(-500, 500), y=rng.uniform(-500, 500), w=120.5, h=80))
    if roll < 0.60:
        return SceneCommand(op=SceneOp.SET_REPRESENTATION, actor=actor, object_id=target,
                            representation=rng.choice(tuple(Representation)))
    if roll < 0.66:
        return SceneCommand(op=SceneOp.SET_VISIBILITY, actor=actor, object_id=target, visibility=rng.choice(tuple(Visibility)))
    if roll < 0.78:
        other = rng.choice((rng.choice(stars), f"{rng.choice(notes)}-{step // 40}"))
        if other == target:  # une relation relie deux objets distincts : la commande ne se construirait pas
            other = rng.choice(stars)
        return SceneCommand(op=SceneOp.LINK, actor=actor, relation=SceneRelation(
            relation_id=f"rel-{rng.randrange(30)}", kind=RelationKind.EXPLAINS, from_id=target, to_id=other,
            layer=rng.choice((50, 60))))
    if roll < 0.84:
        return SceneCommand(op=SceneOp.UNLINK, actor=actor, relation_id=f"rel-{rng.randrange(30)}")
    if roll < 0.87:
        return SceneCommand(op=SceneOp.PIN, actor=SceneActor.USER, object_id=target)
    if roll < 0.90:
        return SceneCommand(op=SceneOp.ATTACH_SIGNAL, actor=actor, object_id=f"sig-{rng.randrange(6)}",
                            fields=SceneObjectFields(category="attention"), target_id=rng.choice(stars))
    # Archive : cerveau ou utilisateur (19/09/2026 : même main), parfois le
    # runtime, hors de sa matrice (refusé : rejected_authority / op_not_allowed).
    # Réalignement baseline : le refus d'autorité du cerveau n'existe plus.
    archiver = actor if rng.random() < 0.85 else SceneActor.RUNTIME
    return SceneCommand(op=SceneOp.ARCHIVE, actor=archiver, object_id=rng.choice((target, rng.choice(stars))))


#: Une commande de sélection s'ajoute toutes les `SELECTION_EVERY` étapes, tirée
#: d'un générateur à part : le parcours de base reste celui d'avant la Slice 03.
SELECTION_EVERY = 8


def random_selection_command(rng: random.Random, snapshot: SceneSnapshot) -> SceneCommand:
    """Commande de sélection (Slice 03, handoff jarvis-mcp-semantic-batch-inspector) : un patch, plusieurs membres.

    Ids explicites tirés de la scène courante (placés pour translater ou
    épingler), parfois un fantôme, un archivé ou un non placé (refus entier) ;
    ou filtres étroits (non placés écartés) ; cascades de signaux à
    l'archivage ; parfois le runtime (refusé).
    """

    # L'archivage de sélection plus rare : les autres archivages gardent déjà la scène clairsemée.
    op = rng.choices((SceneOp.PATCH_SELECTION, SceneOp.TRANSLATE_SELECTION, SceneOp.PIN_SELECTION,
                      SceneOp.UNPIN_SELECTION, SceneOp.ARCHIVE_SELECTION), weights=(4, 4, 4, 4, 1))[0]
    actor = rng.choice((SceneActor.BRAIN, SceneActor.USER)) if rng.random() < 0.92 else SceneActor.RUNTIME
    placed_only = op in (SceneOp.TRANSLATE_SELECTION, SceneOp.PIN_SELECTION)
    present = [item.object_id for item in snapshot.objects if item.geometry is not None or not placed_only]
    if present and rng.random() < 0.75:
        chosen = rng.sample(present, min(len(present), rng.randint(1, 4)))
        if rng.random() < 0.12:
            unplaced = [item.object_id for item in snapshot.objects if item.geometry is None]
            chosen.append(rng.choice(("ghost", *snapshot.archived_ids[-3:], *unplaced[:3])))
        selection = SceneSelection(ids=tuple(dict.fromkeys(chosen)))
    else:
        # Filtre étroit : une catégorie d'une nature, sinon un archivage viderait la scène.
        selection = SceneSelection(kinds=(rng.choice(list(SceneObjectKind)),),
                                   category=rng.choice(("research", "error", "castor")))
    if op is SceneOp.PATCH_SELECTION:
        changes = rng.choice((SelectionChanges(visibility=rng.choice(tuple(Visibility))),
                              SelectionChanges(layer=rng.choice((50, 120)), annotation=rng.choice(("", "à revoir 🚀"))),
                              SelectionChanges(representation=rng.choice(tuple(Representation)), category="castor")))
        return SceneCommand(op=op, actor=actor, selection=selection, changes=changes)
    if op is SceneOp.TRANSLATE_SELECTION:
        delta = SceneDelta(rng.choice((-300, -2.37, 4.5, 250)), rng.choice((0.1, -7, 120)))
        return SceneCommand(op=op, actor=actor, selection=selection, delta=delta, pin=rng.choice((None, True)))
    return SceneCommand(op=op, actor=actor, selection=selection)


def run_sequence(initial: SceneSnapshot, seed: int, count: int) -> tuple[SceneSnapshot, list[dict], list[dict], dict[str, int]]:
    """Plier `count` commandes ; rendre l'état final, les patchs, les instantanés par révision, les issues."""

    rng = random.Random(seed)
    selection_rng = random.Random(seed + 1)
    snapshot = initial
    patches: list[dict] = []
    snapshots = [initial.to_payload()]
    outcomes: dict[str, int] = {}
    for step in range(count):
        commands = [random_command(rng, step)]
        if step % SELECTION_EVERY == SELECTION_EVERY - 1:
            commands.append(random_selection_command(selection_rng, snapshot))
        for command in commands:
            update = apply_scene_command(snapshot, command)
            outcomes[update.outcome.value] = outcomes.get(update.outcome.value, 0) + 1
            key = f"{command.op.value}:{update.outcome.value}"
            outcomes[key] = outcomes.get(key, 0) + 1
            if update.outcome is SceneCommandOutcome.APPLIED:
                assert update.patch is not None
                patches.append(update.patch.to_payload())
                snapshots.append(update.snapshot.to_payload())
            snapshot = update.snapshot
    return snapshot, patches, snapshots, outcomes


def snapshot_response(snapshot: dict, epoch: str = "epoch-1") -> dict:
    return {"source": "core", "core_reachable": True, "scene": {"state": "ready", "code": None},
            "scene_id": snapshot["scene_id"], "epoch": epoch, "revision": snapshot["revision"], "snapshot": snapshot, "error": None}


# --------------------------------------------------------------------- parité


@pytest.mark.parametrize("seed", [20260916, 1, 99, 4242])
def test_the_js_applier_reproduces_the_python_reducer(scene_logic, seed):
    final, patches, _, outcomes = run_sequence(SceneSnapshot(scene_id="scene-parity"), seed=seed, count=1500)

    assert len(patches) > 400 and outcomes.get("rejected_authority", 0) > 0 and outcomes.get("invalid", 0) > 0
    # Slice 03 : chaque commande de sélection est appliquée au moins une fois (un patch, plusieurs membres).
    for op in ("patch_selection", "translate_selection", "pin_selection", "unpin_selection", "archive_selection"):
        assert outcomes.get(f"{op}:applied", 0) > 0, (op, outcomes)
    assert any(sum(op["op"] == "put_object" for op in patch["ops"]) >= 3 for patch in patches)
    kinds = {op["op"] for patch in patches for op in patch["ops"]}
    assert kinds == {"put_object", "archive_object", "put_relation", "delete_relation"}, kinds
    assert final.archived_ids and final.relations

    result = scene_logic(
        """
        let r=S.fromSnapshot(D.initial);if(!r.ok)return {error:r.reason};
        let state=r.state;
        for(const patch of D.patches){const a=S.applyPatch(state,patch);if(!a.ok)return {error:a.reason,at:patch.revision};state=a.state}
        return S.toSnapshot(state);
        """,
        {"initial": snapshot_response(SceneSnapshot(scene_id="scene-parity").to_payload()), "patches": patches},
    )

    assert result == final.to_payload()


def test_tombstone_eviction_at_4096_matches_the_python_reducer(scene_logic):
    """Départ à 4 090 pierres tombales : les archives du parcours en font tomber les plus anciennes."""

    initial = SceneSnapshot(scene_id="scene-evict", revision=7, archived_ids=tuple(f"old-{index}" for index in range(MAX_ARCHIVED_IDS - 6)))
    final, patches, _, _ = run_sequence(initial, seed=7, count=900)

    archives = sum(op["op"] == "archive_object" for patch in patches for op in patch["ops"])
    assert archives > 6, "le parcours doit dépasser la borne"
    assert len(final.archived_ids) == MAX_ARCHIVED_IDS and "old-0" not in final.archived_ids

    result = scene_logic(
        """
        let state=S.fromSnapshot(D.initial).state;
        for(const patch of D.patches){const a=S.applyPatch(state,patch);if(!a.ok)return {error:a.reason};state=a.state}
        return S.toSnapshot(state);
        """,
        {"initial": snapshot_response(initial.to_payload()), "patches": patches},
    )

    assert result == final.to_payload()


# ---------------------------------------------------------------- convergence


def test_the_client_converges_after_gaps_duplicates_bounded_responses_and_a_core_restart(scene_logic):
    final, patches, snapshots, _ = run_sequence(SceneSnapshot(scene_id="scene-converge"), seed=11, count=700)
    assert len(patches) > 150

    result = scene_logic(
        """
        // Serveur simulé : anneau de 16 patchs, réponses bornées à 5, pertes,
        // doublons, trous, et un redémarrage (autre époque) à mi-parcours.
        let seed=12345;const rand=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648};
        const RING=16,CHUNK=5;
        let serverRev=0,epoch='e1',state=null,resyncs=0,reasons={},loops=0;
        const snapshotAt=rev=>({scene_id:D.snapshots[rev].scene_id,epoch,revision:rev,snapshot:D.snapshots[rev],error:null});
        while(loops++<20000){
          if(serverRev<D.patches.length)serverRev=Math.min(D.patches.length,serverRev+1+Math.floor(rand()*4));
          if(loops===60)epoch='e2';  // Core redémarré : même scène, autre époque
          if(!state){
            const got=S.fromSnapshot(snapshotAt(serverRev));if(!got.ok)return {error:got.reason};
            state=got.state;resyncs++;continue;
          }
          if(loops>=20&&loops<32)continue;  // client coupé : l'anneau est dépassé
          const roll=rand();
          if(roll<0.1){const r=S.applyPatchResponse(state,{error:{code:'core_unreachable'}});if(r.action!=='unavailable')return {error:'unavailable'};continue}
          let response;
          const after=state.revision;
          if(serverRev-after>RING){
            response={scene_id:state.scene_id,epoch,revision:serverRev,resync_required:true,more:false,patches:[]};
          }else{
            let list=D.patches.slice(after,serverRev);
            let more=false;
            if(list.length>CHUNK){list=list.slice(0,CHUNK);more=true}
            if(roll<0.2&&list.length>1)list=list.slice(1);                 // trou
            if(roll>=0.2&&roll<0.3&&after>0)list=[D.patches[after-1],...list]; // doublon en retard
            const reached=list.length?list[list.length-1].revision:serverRev;
            response={scene_id:state.scene_id,epoch,revision:more?reached:serverRev,resync_required:false,more,patches:list};
          }
          const r=S.applyPatchResponse(state,response);
          reasons[r.action+':'+r.reason]=(reasons[r.action+':'+r.reason]||0)+1;
          if(r.action==='resync'){state=null;continue}
          state=r.state;
          if(serverRev===D.patches.length&&state.revision===serverRev&&state.epoch===epoch&&r.action!=='more')break;
        }
        return {final:S.toSnapshot(state),resyncs,reasons,epoch:state.epoch};
        """,
        {"patches": patches, "snapshots": snapshots},
    )

    assert result["final"] == final.to_payload()
    assert result["epoch"] == "e2"
    reasons = result["reasons"]
    assert any(key.startswith("resync:gap") for key in reasons), reasons
    assert "resync:epoch_changed" in reasons and "resync:resync_required" in reasons, reasons
    assert "more:" in reasons and "applied:" in reasons, reasons


# ------------------------------------------------------------------ règles


def two_revisions() -> tuple[dict, dict, dict]:
    start = SceneSnapshot(scene_id="scene-rules")
    first = apply_scene_command(start, SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id="art-1",
        fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="research")))
    second = apply_scene_command(first.snapshot, SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id="art-1"))
    return snapshot_response(start.to_payload()), first.patch.to_payload(), second.patch.to_payload()


def test_every_resync_reason_is_signalled_and_nothing_is_half_applied(scene_logic):
    initial, patch1, patch2 = two_revisions()
    result = scene_logic(
        """
        const s0=S.fromSnapshot(D.initial).state;
        const base={scene_id:s0.scene_id,epoch:s0.epoch,resync_required:false,more:false};
        const out={};
        out.gap=S.applyPatchResponse(s0,{...base,revision:2,patches:[D.patch2]});
        out.missing_tail=S.applyPatchResponse(s0,{...base,revision:2,patches:[D.patch1]});
        out.scene=S.applyPatchResponse(s0,{...base,scene_id:'other',revision:1,patches:[D.patch1]});
        out.epoch=S.applyPatchResponse(s0,{...base,epoch:'epoch-2',revision:0,patches:[]});
        out.flag=S.applyPatchResponse(s0,{...base,resync_required:true,revision:9,patches:[]});
        out.none=S.applyPatchResponse(null,{...base,revision:1,patches:[D.patch1]});
        out.error=S.applyPatchResponse(s0,{error:{code:'scene_unavailable'},patches:[]});
        out.ok=S.applyPatchResponse(s0,{...base,revision:2,patches:[D.patch1,D.patch2]});
        out.stale=S.applyPatchResponse(out.ok.state,{...base,revision:2,patches:[D.patch1,D.patch2]});
        out.more=S.applyPatchResponse(s0,{...base,revision:1,more:true,patches:[D.patch1]});
        out.retry=S.applyPatchResponse(s0,{source:'core',core_reachable:null,scene:null,scene_id:null,epoch:null,revision:null,
          patches:[],resync_required:false,more:false,retry_after_ms:1000,error:{code:'patch_waits_busy',message:'x'}});
        out.retry={action:out.retry.action,reason:out.retry.reason,retry_after_ms:out.retry.retry_after_ms,same:out.retry.state===s0};
        // Patch refusé à mi-chemin : l'état reçu reste intact.
        const bad={...D.patch2,ops:[D.patch2.ops[0],{op:'delete_relation',relation_id:'absent'}]};
        const s1=S.applyPatch(s0,D.patch1).state;
        const refused=S.applyPatch(s1,bad);
        out.atomic={ok:refused.ok,reason:refused.reason,still:[...s1.objects.keys()],archived:[...s1.archived_ids]};
        out.rewrite=S.applyPatch(S.applyPatch(s1,D.patch2).state,{...D.patch1,revision:3}).reason;
        out.schema=S.applyPatch(s0,{...D.patch1,schema_version:2}).reason;
        out.query=S.patchQuery(out.ok.state,25);
        const summary=r=>({action:r.action,reason:r.reason,revision:r.state?r.state.revision:null});
        for(const key of ['gap','missing_tail','scene','epoch','flag','none','error','ok','stale','more'])out[key]=summary(out[key]);
        return out;
        """,
        {"initial": initial, "patch1": patch1, "patch2": patch2},
    )

    assert result["gap"] == {"action": "resync", "reason": "gap", "revision": 0}
    assert result["missing_tail"] == {"action": "resync", "reason": "gap", "revision": 1}
    assert result["scene"]["reason"] == "scene_changed" and result["epoch"]["reason"] == "epoch_changed"
    assert result["flag"] == {"action": "resync", "reason": "resync_required", "revision": 0}
    assert result["none"] == {"action": "resync", "reason": "no_state", "revision": None}
    assert result["error"] == {"action": "unavailable", "reason": "scene_unavailable", "revision": 0}
    assert result["ok"] == {"action": "applied", "reason": "", "revision": 2}
    assert result["stale"] == {"action": "unchanged", "reason": "", "revision": 2}
    assert result["more"] == {"action": "more", "reason": "", "revision": 1}
    assert result["retry"] == {"action": "retry", "reason": "patch_waits_busy", "retry_after_ms": 1000, "same": True}
    assert result["atomic"] == {"ok": False, "reason": "delete_unknown_relation", "still": ["art-1"], "archived": []}
    assert result["rewrite"] == "rewrite_archived_object"
    assert result["schema"] == "invalid_patch"
    assert result["query"] == {"scene_id": "scene-rules", "epoch": "epoch-1", "after": 2, "wait_s": 25}


def test_a_snapshot_never_rewinds_the_same_epoch_but_a_new_epoch_replaces_it(scene_logic):
    result = scene_logic(
        """
        const held={scene_id:'s',epoch:'e1',revision:5};
        const r=(scene_id,epoch,revision)=>({scene_id,epoch,revision,snapshot:{}});
        return [S.acceptSnapshot(null,r('s','e1',0)),S.acceptSnapshot(held,r('s','e1',6)),S.acceptSnapshot(held,r('s','e1',5)),
          S.acceptSnapshot(held,r('s','e1',4)),S.acceptSnapshot(held,r('s','e2',1)),S.acceptSnapshot(held,r('t','e1',1)),
          S.acceptSnapshot(held,{error:{code:'core_unreachable'}}),S.fromSnapshot({error:{code:'x'}}).reason,
          S.fromSnapshot({scene_id:'s',epoch:'e',revision:1,snapshot:{schema_version:1,scene_id:'s',revision:2,objects:[],relations:[],archived_ids:[]}}).reason];
        """,
    )

    assert result == [True, True, True, False, True, True, False, "no_snapshot", "invalid_snapshot"]


async def test_the_page_serves_the_same_file_and_exposes_only_the_client(tmp_path):
    html = (CONTROL_CENTER_SCENE_JS.with_name("control_center.html")).read_text(encoding="utf-8")
    assert SCENE_SCRIPT_MARKER in html

    served = (await ControlCenter(runtime_root=tmp_path, project_root=tmp_path).index(None)).text

    assert SCENE_SCRIPT_MARKER not in served
    assert CONTROL_CENTER_SCENE_JS.read_text(encoding="utf-8") in served
    source = CONTROL_CENTER_SCENE_JS.read_text(encoding="utf-8")
    # Pur : ni DOM, ni réseau, ni minuterie ; un seul nom global.
    for forbidden in ("document.", "fetch(", "setTimeout", "setInterval", "XMLHttpRequest", "addEventListener"):
        assert forbidden not in source, forbidden
    assert "root.JarvisSceneClient=api" in source
