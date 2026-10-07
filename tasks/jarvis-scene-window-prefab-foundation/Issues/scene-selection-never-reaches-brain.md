# Scene selection never reaches the brain

Found by: Slice 00 audit (2026-10-03). Status: open.

(feedback 2026-09-22 §1): "this window" is still resolved by guessing. Prefab `notify` events don't solve this. It needs its own small task: a selection fact in `BrainContext`, using the same channel this task adds to.
