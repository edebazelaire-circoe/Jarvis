"""Surface de navigation (Tool Brain S7, lot 07b) : domaine pur `jarvis.domain.browser_surface`.

Contrat : `docs/tool-brain-contracts.md` §15. Ce qui doit tenir : sûreté des URL (http/https publics seulement), id
`surf_<opaque>` stable et sans collision avec l'id de scène, historique borné qui coupe l'avant, zoom par crans,
défilement borné, *focus* = composition de scène existante, et chaque plan accepté par le **vrai** réducteur
(`apply_scene_command`) ; la validation du bloc prefab par le manifeste livré est prouvée dans
`test_tool_brain_adapters.py` (Core réel).
"""

from __future__ import annotations

import pytest

from jarvis.domain.browser_surface import (
    MAX_HISTORY, NO_HISTORY, SURFACE_PREFAB_ID, UNKNOWN_SURFACE, UNSAFE_URL, ZOOM_STEPS, SurfaceError,
    check_surface_url, plan_focus, plan_history, plan_open, plan_scroll, plan_zoom, surface_id_of, surfaces_of,
)
from jarvis.domain.scene import (
    MAX_LAYER, SceneActor, SceneCommand, SceneCommandOutcome, SceneObjectFields, SceneObjectKind, SceneOp,
    ScenePayload, SceneSnapshot, Visibility, apply_scene_command,
)


def _run(snapshot: SceneSnapshot, command: SceneCommand) -> SceneSnapshot:
    update = apply_scene_command(snapshot, command)
    assert update.outcome is SceneCommandOutcome.APPLIED, (update.outcome, update.reason, update.detail)
    return update.snapshot


def _open(snapshot: SceneSnapshot, url: str, opaque: str = "aaaaaaaaaaaa", **kw) -> tuple[SceneSnapshot, str]:
    after = _run(snapshot, plan_open(snapshot, url, new_opaque=opaque, **kw))
    return after, surfaces_of(after)[0].surface_id


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,<script>1</script>", "file:///c:/windows/win.ini", "blob:https://x/y",
    "vbscript:x", "ftp://example.com/a", "//example.com/a", "https://user:pw@example.com/", "https://@example.com/",
    "http://127.0.0.1/", "http://localhost:8080/", "http://app.localhost/", "http://[::1]/", "http://10.0.0.5/",
    "http://192.168.1.1/", "http://169.254.169.254/", "http://[::ffff:10.0.0.1]/", "http://2130706433/",
    "http://0x7f.1/", "http://127.1/", "http://printer.local/", "https://exa mple.com/", "https://example.com/\n",
    " https://example.com", "https://", "", None, 5, "https://example.com:99999/", "http://" + "a" * 2050,
    "https://bücher.example/",
])
def test_unsafe_urls_are_refused_with_a_typed_code(url):
    with pytest.raises(SurfaceError) as raised:
        check_surface_url(url)
    assert raised.value.code == UNSAFE_URL


@pytest.mark.parametrize("url", ["https://example.com/a?b=c#d", "http://www.sqlite.org", "https://8.8.8.8/",
                                 "https://example.com:8443/x", "HTTPS://Example.com/", "https://xn--bcher-kva.example/"])
def test_public_http_and_https_urls_are_accepted(url):
    assert check_surface_url(url).lower().startswith(("http://", "https://"))


def test_surface_id_is_opaque_stable_and_not_the_scene_id():
    first = surface_id_of("brain-window-aaaaaaaaaaaa")
    assert first == surface_id_of("brain-window-aaaaaaaaaaaa")
    assert first.startswith("surf_") and len(first) == len("surf_") + 12 and "aaaaaaaaaaaa" not in first
    assert first != surface_id_of("brain-window-bbbbbbbbbbbb")


def test_open_creates_a_prefab_window_surface_and_registers_it_in_the_scene_read():
    snapshot, surface_id = _open(SceneSnapshot(scene_id="s"), "https://example.com/a", label="Exemple", note="Des notes")
    item = snapshot.get_object("brain-window-aaaaaaaaaaaa")
    assert item.kind is SceneObjectKind.WINDOW and item.payload.prefab.prefab_id == SURFACE_PREFAB_ID
    assert item.payload.title == "Exemple" and item.origin is SceneActor.BRAIN
    (surface,) = surfaces_of(snapshot)
    assert surface.surface_id == surface_id == surface_id_of(item.object_id)
    assert surface.meta() == {"url": "https://example.com/a", "host": "example.com", "position": 1, "pages": 1,
                              "zoom": 100, "scroll": 0, "visible": True, "can_back": False, "can_forward": False}
    assert item.payload.prefab.data["body"] == "Des notes"


def test_open_in_an_existing_surface_pushes_history_cuts_the_forward_part_and_resets_scroll():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    for number in (2, 3):
        snapshot = _run(snapshot, plan_open(snapshot, f"https://example.com/{number}", surface_id=sid))
    snapshot = _run(snapshot, plan_scroll(snapshot, sid, "bottom"))
    snapshot = _run(snapshot, plan_history(snapshot, sid, "back"))
    snapshot = _run(snapshot, plan_history(snapshot, sid, "back"))
    assert surfaces_of(snapshot)[0].page.url == "https://example.com/1"
    snapshot = _run(snapshot, plan_open(snapshot, "https://example.com/9", surface_id=sid))
    (surface,) = surfaces_of(snapshot)
    assert [page.url for page in surface.history] == ["https://example.com/1", "https://example.com/9"]
    assert (surface.index, surface.scroll) == (1, 0)


def test_open_the_current_address_again_changes_nothing():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    update = apply_scene_command(snapshot, plan_open(snapshot, "https://example.com/1", surface_id=sid))
    assert update.outcome is SceneCommandOutcome.DUPLICATE


def test_history_is_bounded_and_drops_the_oldest_page():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/0")
    for number in range(1, MAX_HISTORY + 5):
        snapshot = _run(snapshot, plan_open(snapshot, f"https://example.com/{number}", surface_id=sid))
    (surface,) = surfaces_of(snapshot)
    assert len(surface.history) == MAX_HISTORY and surface.index == MAX_HISTORY - 1
    assert surface.history[0].url == "https://example.com/5"


def test_back_and_forward_walk_the_trail_and_refuse_at_the_edges():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    with pytest.raises(SurfaceError) as raised:
        plan_history(snapshot, sid, "back")
    assert raised.value.code == NO_HISTORY
    snapshot = _run(snapshot, plan_open(snapshot, "https://example.com/2", surface_id=sid))
    snapshot = _run(snapshot, plan_history(snapshot, sid, "back"))
    assert surfaces_of(snapshot)[0].page.url == "https://example.com/1"
    snapshot = _run(snapshot, plan_history(snapshot, sid, "forward"))
    assert surfaces_of(snapshot)[0].page.url == "https://example.com/2"
    with pytest.raises(SurfaceError) as raised:
        plan_history(snapshot, sid, "forward")
    assert raised.value.code == NO_HISTORY
    with pytest.raises(SurfaceError):
        plan_history(snapshot, sid, "sideways")


def test_scroll_moves_by_quarters_and_stops_at_the_edges():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    seen = []
    for direction in ("down", "down", "bottom", "up", "top"):
        snapshot = _run(snapshot, plan_scroll(snapshot, sid, direction))
        seen.append(surfaces_of(snapshot)[0].scroll)
    assert seen == [25, 50, 100, 75, 0]
    assert apply_scene_command(snapshot, plan_scroll(snapshot, sid, "up")).outcome is SceneCommandOutcome.DUPLICATE
    with pytest.raises(SurfaceError):
        plan_scroll(snapshot, sid, "left")


def test_zoom_steps_through_the_scale_and_stops_at_the_ends():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    levels = []
    for _ in range(len(ZOOM_STEPS)):
        snapshot = _run(snapshot, plan_zoom(snapshot, sid, "in")) if surfaces_of(snapshot)[0].zoom < 300 else snapshot
        levels.append(surfaces_of(snapshot)[0].zoom)
    assert levels[:4] == [125, 150, 200, 300] and levels[-1] == 300
    assert apply_scene_command(snapshot, plan_zoom(snapshot, sid, "in")).outcome is SceneCommandOutcome.DUPLICATE
    snapshot = _run(snapshot, plan_zoom(snapshot, sid, "reset"))
    assert surfaces_of(snapshot)[0].zoom == 100
    for _ in range(3):
        snapshot = _run(snapshot, plan_zoom(snapshot, sid, "out"))
    assert surfaces_of(snapshot)[0].zoom == 25
    assert apply_scene_command(snapshot, plan_zoom(snapshot, sid, "out")).outcome is SceneCommandOutcome.DUPLICATE
    with pytest.raises(SurfaceError):
        plan_zoom(snapshot, sid, "huge")


def test_focus_shows_unfolds_and_raises_above_every_visible_object():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    other = _run(snapshot, SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-window-bbbbbbbbbbbb",
                                        fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="note",
                                                                 payload=ScenePayload(title="Autre"), layer=500)))
    hidden = _run(other, SceneCommand(op=SceneOp.SET_VISIBILITY, actor=SceneActor.BRAIN,
                                      object_id="brain-window-aaaaaaaaaaaa", visibility=Visibility.HIDDEN))
    focused = _run(hidden, plan_focus(hidden, sid))
    item = focused.get_object("brain-window-aaaaaaaaaaaa")
    assert item.visibility is Visibility.VISIBLE and item.layer == 501
    assert apply_scene_command(focused, plan_focus(focused, sid)).outcome is SceneCommandOutcome.DUPLICATE


def test_focus_at_the_top_layer_uses_the_order_and_a_lone_surface_is_already_in_front():
    snapshot, sid = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    assert apply_scene_command(snapshot, plan_focus(snapshot, sid)).outcome is SceneCommandOutcome.DUPLICATE
    crowded = _run(snapshot, SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN,
                                          object_id="brain-window-bbbbbbbbbbbb",
                                          fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="note",
                                                                   layer=MAX_LAYER, order=7)))
    focused = _run(crowded, plan_focus(crowded, sid))
    item = focused.get_object("brain-window-aaaaaaaaaaaa")
    assert (item.layer, item.order) == (MAX_LAYER, 8)


def test_unknown_surface_ids_are_refused_for_every_verb():
    snapshot, _ = _open(SceneSnapshot(scene_id="s"), "https://example.com/1")
    for call in (lambda: plan_focus(snapshot, "surf_000000000000"), lambda: plan_zoom(snapshot, "brain-window-aaaaaaaaaaaa", "in"),
                 lambda: plan_open(snapshot, "https://example.com/2", surface_id="surf_nope"),
                 lambda: plan_history(snapshot, "x", "back"), lambda: plan_scroll(snapshot, "x", "top")):
        with pytest.raises(SurfaceError) as raised:
            call()
        assert raised.value.code == UNKNOWN_SURFACE


def test_a_plain_window_is_not_a_surface():
    snapshot = _run(SceneSnapshot(scene_id="s"), SceneCommand(
        op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-window-cccccccccccc",
        fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="note", payload=ScenePayload(title="x"))))
    assert surfaces_of(snapshot) == () and surfaces_of(None) == ()
