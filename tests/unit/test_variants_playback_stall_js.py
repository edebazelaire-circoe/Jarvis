"""Chien de garde de la lecture continue de Variantes (plainte : « la lecture se bloque au bout de quelques secondes »).

Le séquenceur n'avançait que sur les rapports d'horloge du Player. Trois blocages sans reprise :
rapports qui s'arrêtent, premier rapport trop tardif (verrou `synced`), scène tuée. Le chien de garde (`STALL_MS` sans progrès
pendant la phase `playing`) relit l'horloge de l'hôte, rend l'ordre de lecture, puis met la lecture en échec visible
(`playback_stalled`, « Réessayer »). Un onglet caché n'est pas un blocage.

Note : l'hôte rapporte une scène tuée comme issue `failed` de raison `killed` (control_center_prefab_host.js, `fail(..., 'killed')`) ;
`onOutcome` la traite donc déjà comme un échec de scène.
"""

from __future__ import annotations

from tests.unit.test_continuous_sequencing_js import SEQ_BENCH, run_seq

assert "variantChanged:()=>{changedVariant++}" in SEQ_BENCH
BENCH = "let VIS={v:true};\n" + SEQ_BENCH.replace(
    "variantChanged:()=>{changedVariant++}", "visible:()=>VIS.v,variantChanged:()=>{changedVariant++}", 1
) + r"""
const step=(ms)=>{for(let i=0;i<ms/1000;i++)hb.advance(1000)};
let hb=null;
const bench=(o)=>{hb=seqBench(o);return hb};
"""


def run(tmp_path, body):
    import tests.unit.test_continuous_sequencing_js as base

    saved = base.SEQ_BENCH
    base.SEQ_BENCH = BENCH
    try:
        return run_seq(tmp_path, body)
    finally:
        base.SEQ_BENCH = saved


async def test_reports_that_stop_mid_scene_are_never_a_silent_playing_state(tmp_path):
    result = run(tmp_path, r"""
      const b=bench({parkAhead:true});
      await b.seq.play();
      [0,10,20].forEach(f=>b.report(f,true));
      step(16000);                                  // the Player never reports again
      const v=b.seq.view();
      return {phase:v.phase,code:v.error&&v.error.code,message:v.error&&v.error.message,sceneId:v.error&&v.error.scene_id,
        logs:b.logs.map(l=>l[0]),plays:b.orders.filter(o=>o[1]==='play').length};
    """)
    assert result["phase"] == "failed", "playback froze silently in 'playing'"
    assert result["code"] == "playback_stalled" and result["sceneId"] == "pss_1"
    assert "Réessayer" in result["message"]
    assert result["plays"] >= 2, "the play order was never re-sent"
    for key in ("sequencer_stall_detected", "sequencer_stall_failed"):
        assert key in result["logs"], key


async def test_a_lost_report_is_healed_by_ordering_play_again_from_where_the_player_stood(tmp_path):
    result = run(tmp_path, r"""
      const b=bench({parkAhead:true});
      await b.seq.play();
      [0,10,20].forEach(f=>b.report(f,true));
      step(5000);                                   // silence: one recovery re-sends play
      const replays=b.orders.filter(o=>o[1]==='play');
      b.playTo(20,89,10);                           // the Player answers again
      const atEnd={phase:b.seq.view().phase,shows:b.shows.slice()};
      return {replays,atEnd,logs:b.logs.map(l=>l[0])};
    """)
    assert len(result["replays"]) == 2 and 15 <= result["replays"][1][2] <= 25
    assert result["atEnd"]["phase"] in ("playing", "waiting") and result["atEnd"]["shows"][-1] == 1, "playback went on to the next scene"
    assert "sequencer_stall_detected" in result["logs"]


async def test_a_first_report_that_arrives_late_does_not_freeze_the_end_of_the_scene(tmp_path):
    result = run(tmp_path, r"""
      const b=bench({parkAhead:true});
      await b.seq.play();
      b.report(60,true);                            // first report after the order: later than one second of playback
      b.report(89,false);                           // the scene ended; the sequencer never believed any of it
      const before=b.shows.slice();
      step(6000);
      const shows=b.shows.slice();
      b.swap();
      return {before,shows,phase:b.seq.view().phase,last:b.orders[b.orders.length-1]};
    """)
    assert result["before"] == []
    assert result["shows"][-1] == 1, "the end of the scene was never detected: frozen on the last frame"
    assert result["phase"] == "playing" and result["last"] == ["s2@1", "play", 0]


async def test_a_hidden_tab_is_not_a_stall(tmp_path):
    result = run(tmp_path, r"""
      const b=bench({parkAhead:true});
      await b.seq.play();
      [0,10,20].forEach(f=>b.report(f,true));
      VIS.v=false;
      step(30000);
      const hidden={phase:b.seq.view().phase,plays:b.orders.filter(o=>o[1]==='play').length,logs:b.logs.map(l=>l[0])};
      VIS.v=true;
      step(2000);                                   // just back: the stall clock starts over
      const back={phase:b.seq.view().phase,plays:b.orders.filter(o=>o[1]==='play').length};
      return {hidden,back};
    """)
    assert result["hidden"]["phase"] == "playing" and result["hidden"]["plays"] == 1
    assert "sequencer_stall_detected" not in result["hidden"]["logs"]
    assert result["back"] == {"phase": "playing", "plays": 1}


async def test_a_pause_or_a_healthy_playback_leaves_no_watchdog_behind(tmp_path):
    result = run(tmp_path, r"""
      const b=bench({parkAhead:true});
      await b.seq.play();
      [0,10,20].forEach(f=>b.report(f,true));
      b.seq.pause();
      const before=b.orders.length;
      step(30000);
      const paused={phase:b.seq.view().phase,sent:b.orders.length-before,logs:b.logs.map(l=>l[0]).filter(k=>k.includes('stall'))};
      const c=bench({parkAhead:true});
      await c.seq.play();
      for(let f=0;f<=80;f+=10){c.report(f,true);step(1000)}   // 9 s of steady reports: never a stall
      return {paused,steady:{phase:c.seq.view().phase,logs:c.logs.map(l=>l[0]).filter(k=>k.includes('stall'))}};
    """)
    assert result["paused"] == {"phase": "paused", "sent": 0, "logs": []}
    assert result["steady"] == {"phase": "playing", "logs": []}


async def test_after_a_stall_failure_retry_resumes_playback(tmp_path):
    result = run(tmp_path, r"""
      const b=bench({parkAhead:true});
      await b.seq.play();
      [0,10,20].forEach(f=>b.report(f,true));
      step(16000);
      const failed=b.seq.view().phase;
      const plays=b.orders.filter(o=>o[1]==='play').length;
      await b.seq.retry();
      const after={phase:b.seq.view().phase,plays:b.orders.filter(o=>o[1]==='play').length,err:b.seq.view().error};
      const ordered=b.orders.filter(o=>o[1]==='play').pop()[2];
      b.playTo(ordered,89,10);
      return {failed,plays,after,shows:b.shows.slice()};
    """)
    assert result["failed"] == "failed"
    assert result["after"]["phase"] == "playing" and result["after"]["err"] is None
    assert result["after"]["plays"] == result["plays"] + 1
    assert result["shows"][-1] == 1, "playback went on to the next scene after Réessayer"
