"""Banc des preuves navigateur de l'inspecteur du Studio (jarvis-interactive-presentation-studio, Slice 07).

Rien n'est simule sauf l'ecran sans tete : un VRAI Core (`JarvisCoreApplication` derriere le vrai `LocalProtocolServer`, racine de
donnees et ports a lui, jamais le Jarvis vivant), le VRAI Control Center qui sert la page et relaie vers lui, un VRAI Chrome piloté
par CDP (`tests/unit/_presentation_studio_inspector_browser.mjs`). Le prefab de la scene est un prefab `custom` publie par la vraie
route `POST /v1/prefabs` : `lab.dial`, dont le manifeste declare un reglage de chaque type que l'inspecteur sait rendre (texte, texte
long, URL, tableau JSON, couleur, degrade, interrupteur, choix court, choix long, curseur reel, curseur entier, entier, nombre libre).
Aucun reglage n'a de code propre dans l'inspecteur : tout vient de l'introspection.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from jarvis.runtime.interaction_mode_view import CoreInteractionModeTransport, CoreInteractionModeView
from jarvis.runtime.scene_view import CoreSceneTransport, CoreSceneView
from tests.unit.test_fullscreen_browser import _chrome
from tests.unit.test_presentation_studio_routes import AUTH, Core, variant_body

HARNESS = Path(__file__).resolve().parents[1] / "unit" / "_presentation_studio_inspector_browser.mjs"
PREFAB_ID = "lab.dial"
S1, S2, S3 = "pss_0000000000d1", "pss_0000000000d2", "pss_0000000000d3"
PREVIEW_OBJECT = "studio-inspector-preview"

TEMPLATE = """<section id="dial" class="dial">
  <h2 data-jv-text="props.title"></h2>
  <div class="orb" aria-hidden="true"></div>
  <p class="body" data-jv-text="data.body"></p>
</section>
"""
STYLE = """.dial { padding: 12px; color: var(--jv-text); }
.orb { width: calc(40px * var(--size, 1)); height: calc(40px * var(--size, 1)); border-radius: 50%;
  background: linear-gradient(135deg, var(--jv-prop-accent, #6ee7ff), var(--stop2, #a78bfa)); }
"""
BEHAVIOR = """function paint() {
  var p = jarvis.props, root = document.documentElement.style;
  root.setProperty('--size', String(p.size === undefined ? 1 : p.size));
  root.setProperty('--tilt', String(p.tilt === undefined ? 0 : p.tilt));
  root.setProperty('--stop2', (p.palette && p.palette[1]) || '#a78bfa');
  document.documentElement.setAttribute('data-layout', p.layout || 'center');
  document.documentElement.setAttribute('data-glow', p.glow ? 'on' : 'off');
}
jarvis.on('init', paint);
jarvis.on('update', paint);
"""


def lab_manifest() -> dict:
    def prop(kind: str, description: str, **extra) -> dict:
        return {"type": kind, "description": description, **extra}

    return {
        "schema": "jarvis.prefab", "schema_version": 1, "id": PREFAB_ID, "version": 1, "title": "Cadran de laboratoire",
        "description": "Prefab de test de l'inspecteur : un reglage de chaque type.", "family": "window",
        "tags": ["test", "inspecteur"], "aliases": ["cadran"],
        "scene": {"kind": "window", "default_size": {"w": 40, "h": 24}},
        "inputs": {
            "props": {"type": "object", "properties": {
                "title": prop("string", "Le titre.", max_length=40, default="Titre"),
                "code": prop("string", "Trois majuscules.", max_length=3, pattern="^[A-Z]{3}$", default="ABC"),
                "accent": prop("color", "La couleur d'accent.", default="#6ee7ff"),
                "palette": prop("array", "Les etapes du degrade.", max_items=5, default=["#6ee7ff", "#a78bfa"],
                                items={"type": "color"}),
                "glow": prop("boolean", "Halo lumineux.", default=False),
                "layout": prop("enum", "Alignement du contenu.", values=["center", "left", "right"], default="center"),
                "size": prop("number", "Taille de l'orbe.", min=0.5, max=2, default=1),
                "tilt": prop("integer", "Inclinaison en degres.", min=-15, max=15, default=0),
                "speed": prop("integer", "Duree de l'animation en ms.", min=100, max=2000, default=600),
                "delay": prop("number", "Delai avant l'entree, en secondes.", min=0, default=0),
                "easing": prop("enum", "La courbe d'animation.",
                               values=["linear", "ease", "ease-in", "ease-out", "ease-in-out", "spring"], default="ease"),
            }},
            "data": {"type": "object", "properties": {
                "body": prop("text", "Le texte courant.", max_length=400, default=""),
                "link": prop("url", "Un lien."),
                "tags": prop("array", "Des mots-cles.", max_items=6, default=[], items={"type": "string", "max_length": 30}),
            }},
        },
        "sample": {"props": {}, "data": {"body": "Exemple"}},
        "files": {"template": "template.html", "style": "style.css", "behavior": "behavior.js"},
    }


def _control(control_id: str, path: str, label: str, group: str, meaning: str, **bounds) -> dict:
    control = {"control_id": control_id, "path": path, "label": label, "group": group, "meaning": meaning}
    if bounds:
        control["bounds"] = bounds
    return control


#: Les reglages cures de la scene 1 : un par type de widget, dans l'ordre de l'auteur.
CONTROLS = [
    _control("title", "props.title", "Titre", "content", "Le titre affiché en grand."),
    _control("body", "data.body", "Texte", "content", "Le texte courant de la scène.", max_length=300),
    _control("link", "data.link", "Lien", "content", "Une adresse à ouvrir depuis la scène."),
    _control("tags", "data.tags", "Mots-clés", "content", "Des mots-clés pour la recherche."),
    _control("code", "props.code", "Code", "content", "Trois majuscules (le modèle impose la forme)."),
    _control("accent", "props.accent", "Couleur d'accent", "visual", "La couleur qui porte l'attention."),
    _control("palette", "props.palette", "Dégradé", "visual", "Les étapes de couleur du dégradé."),
    _control("glow", "props.glow", "Halo", "visual", "Un halo lumineux autour de l'orbe."),
    _control("layout", "props.layout", "Alignement", "layout", "Où se place le contenu."),
    _control("size", "props.size", "Taille", "layout", "La taille de l'orbe (bornes resserrées par l'auteur).", min=0.6, max=1.8),
    _control("tilt", "props.tilt", "Inclinaison", "layout", "Inclinaison en degrés."),
    _control("speed", "props.speed", "Durée", "motion", "Durée de l'animation d'entrée, en millisecondes."),
    _control("delay", "props.delay", "Délai", "motion", "Délai avant l'entrée, en secondes."),
    _control("easing", "props.easing", "Courbe", "motion", "La courbe d'accélération."),
]


def scene_body(scene_id: str, title: str, controls: list[dict], *, section: str = "") -> dict:
    return {"scene_id": scene_id, "prefab": {"id": PREFAB_ID, "version": 1}, "title": title, "section": section,
            "props": {"title": title, "accent": "#6ee7ff", "size": 1}, "data": {"body": "Bonjour"}, "controls": controls}


SCENES = [
    scene_body(S1, "Ouverture", CONTROLS, section="Début"),
    scene_body(S2, "Chiffres", [c for c in CONTROLS if c["control_id"] in ("title", "accent", "size")]),
    scene_body(S3, "Sans réglage", []),
]


class InspectorRig:
    """`async with InspectorRig(tmp_path) as rig` : Core + Control Center + une presentation de 3 scenes (`rig.pid`, `rig.vid`)."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.core = Core(tmp_path)

    async def __aenter__(self) -> InspectorRig:
        await self.core.__aenter__()
        stack = self.core.stack
        port = int(stack.core_url.rsplit(":", 1)[1])
        token_file = stack.tmp_path / "core.token"
        # What `jarvis/app.py` wires: the scene proxy (the page polls it) and the mode proxy (the HUD).
        stack.center.scene_view = CoreSceneView(CoreSceneTransport(host="127.0.0.1", port=port, token_file=token_file))
        stack.center.interaction_mode_view = CoreInteractionModeView(
            CoreInteractionModeTransport(host="127.0.0.1", port=port, token_file=token_file))
        await self.publish_prefab()
        self.pid, self.vid, self.revision = await self.new_presentation("Atelier du cadran")
        self.url = f"http://127.0.0.1:{stack.cc_port}/"
        return self

    async def __aexit__(self, *exc) -> None:
        await self.core.stack.center.scene_view.aclose()
        await self.core.__aexit__(*exc)

    async def publish_prefab(self) -> None:
        candidate = {"manifest": lab_manifest(), "template": TEMPLATE, "style": STYLE, "behavior": BEHAVIOR}
        async with self.core.http.post(self.core.stack.core_url + "/v1/prefabs", headers=AUTH,
                                       json={"actor": "user", "candidate": candidate}) as response:
            body = await response.json(content_type=None)
            assert response.status == 201, body

    async def new_presentation(self, title: str, *, art_direction: bool = True) -> tuple[str, str, int]:
        _, created = await self.core.call("POST", "", json={"title": title})
        pid, variant = created["presentation"]["presentation_id"], created["variants"][0]
        vid = variant["variant_id"]
        status, saved = await self.core.call("PUT", f"/{pid}/variants/{vid}", json=variant_body(variant, scenes=SCENES))
        assert status == 200, saved
        revision = saved["revision"]
        if art_direction:
            status, made = await self.core.call("POST", f"/{pid}/variants/{vid}/art-direction/fallback",
                                                json={"expected_variant_revision": revision})
            assert status == 201, made
            revision += 1
        return pid, vid, revision

    def variant_file(self, pid: str | None = None, vid: str | None = None) -> Path:
        return self.tmp_path / "data" / "presentations" / (pid or self.pid) / "variants" / f"{vid or self.vid}.json"

    async def edit(self, mutation: dict, *, actor: str = "brain", mode: str = "commit", pid=None, vid=None) -> dict:
        """The Core edit route as a given actor (the voice's door): `mutation` = `{ops: [...]}`; the basis is read fresh."""

        pid, vid = pid or self.pid, vid or self.vid
        _, variant = await self.core.call("GET", f"/{pid}/variants/{vid}")
        body = {"actor": actor, "mode": mode, "basis": {"variant_revision": variant["revision"]}, **mutation}
        _, result = await self.core.call("POST", f"/{pid}/variants/{vid}/edits", json=body)
        return result


def drive_sync(url: str, plan: list, *, viewport: str = "1280x720", reduced_motion: bool = False, timeout: int = 240) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    env = {**os.environ, "CDP_VIEWPORT": viewport}
    if reduced_motion:
        env["CDP_REDUCED_MOTION"] = "1"
    done = subprocess.run([node, str(HARNESS), url, _chrome(), json.dumps(plan)], capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, check=False, env=env)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


async def drive(url: str, plan: list, **kwargs) -> dict:
    # The blocking subprocess runs in a thread so the event loop keeps serving Core and the Control Center.
    return await asyncio.to_thread(drive_sync, url, plan, **kwargs)
