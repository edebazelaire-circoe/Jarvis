"""Deterministic companion of the playback release gate (handoff jarvis-remotion-native-studio-playback-fix, Slice 03).

`control_center_prefab_host.js` executed by node with a fake DOM and a manual clock (the bench of `test_remotion_continuity_js.py`).
The real-browser gate (`test_presentation_playback_release_gate_browser.py`) showed, in a chained play, scenes without anchor never shown
(held 51-78 s, then skipped) and the outgoing Player redrawn with the incoming scene's values. These two tests pin the host-side
mechanism without a browser, so a fix is proven in milliseconds:

- the scene being entered was preloaded beside the live one; `mount(B)` defers its take-over (`later(()=>takeOver(waiting),...)`) and the
  next scene's `preload(C)` arrives before that timer: `dropNext` discards B, which is then never shown;
- `mount(B)` writes B's values into the LIVE record (`update()` targets `frames.get(objectId)`, the outgoing scene A), so A's Player
  repaints A's composition with B's props for the swap window.

Binding target: `docs/presentation-studio.md` > *Presentation experience contract* § 4.2 (crosses every boundary, no blank, no visible
remount, scene k+1 on its local frame 0). Fixed by Slice 05 (queued preload, incoming values go to the incoming frame only); now regression guards.
"""

from __future__ import annotations

import pytest

from tests.unit.test_remotion_continuity_js import HOST_BENCH
from tests.unit.test_remotion_stage_js import run_stage_node

C_PREFAB = "const C='presentation-studio.p000000000001.s000000000003';\n"


def run(tmp_path, body: str) -> dict:
    """A crashed node bench is a harness failure, never the expected failure (the marks accept `AssertionError` only)."""

    try:
        return run_stage_node(tmp_path, HOST_BENCH + C_PREFAB + body)
    except AssertionError as error:   # run_stage_node asserts node's exit code
        pytest.fail(f"harness: node bench failed: {str(error)[:600]}")


# A is live and playing; B (the next scene) was preloaded beside it and is parked, paused on frame 0.
SETUP = r"""
  const b=hostBench();
  b.host.mount(b.slot,b.inst(b.A,{props:{title:'A'}}));
  const live=await b.bringUp(b.A);
  b.c.advance(2000);
  if(!b.host.preload('stage',b.inst(b.B,{props:{title:'B'}})))throw new Error('harness: preload of B refused');
  const next=await b.bringUp(b.B);
  b.c.advance(2000);
  if(!b.host.parked('stage'))throw new Error('harness: B is not parked beside A');
"""


async def test_the_next_preload_never_discards_the_scene_being_entered(tmp_path):
    """Core enters B (`mount(B)`) and, in the same timeline event, announces C (`preload(C)`): B takes the screen, C waits beside it."""

    result = run(tmp_path, SETUP + r"""
      b.host.mount(b.slot,b.inst(b.B,{props:{title:'B'}}));        // the score reached B (same values: take-over deferred by 0 ms)
      b.host.preload('stage',b.inst(C,{props:{title:'C'}}));      // the same timeline event already names the scene after B
      await flush();
      b.c.advance(1);await flush();
      b.c.advance(500);
      return {key:b.host.key('stage'),pending:b.host.pendingKey('stage'),nextConnected:b.frames().includes(next),
              nextStaged:next.className.includes('sc-prefab-staged')};
    """)
    assert result["key"].endswith("s000000000002@1"), f"the screen still shows {result['key']}: the entered scene B was dropped"
    assert result["nextConnected"] is True and result["nextStaged"] is False, result
    assert (result["pending"] or "").endswith("s000000000003@1"), "C waits beside B"


async def test_the_outgoing_player_never_receives_the_incoming_scene_values(tmp_path):
    """Entering B never repaints A's composition with B's values: A's frame gets no `props` message after the swap begins."""

    result = run(tmp_path, SETUP + r"""
      const before=live.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').length;
      b.host.mount(b.slot,b.inst(b.B,{props:{title:'B'}}));
      const sent=live.contentWindow.posted.map(p=>p.message).filter(m=>m.type==='props').slice(before).map(m=>m.props&&m.props.title);
      return {sent};
    """)
    assert result["sent"] == [], f"the outgoing Player A was sent the incoming scene's values: {result['sent']}"
