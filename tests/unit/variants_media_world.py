"""Banc réel du son et du plein écran de Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 08).

Réutilise le banc des Slices 03 à 06 (`RemotionStack`, `_remotion_stage_browser.mjs`, `presentation_playback_gate_world`) et ajoute ce
qu'il faut pour MESURER le son et la mise en page :

- `make_media_deck` : quatre scènes Remotion de formats différents (16:9 en 1920x1080, 4:3, 9:16, 1:1), les deux premières avec un vrai
  `<Audio src={staticFile("tone.wav")}>` (un WAV de 4 s écrit ici, octets réels) ;
- `drive_media` : le pilote CDP partagé avec des arguments de Chrome en plus (`CDP_CHROME_ARGS`, seulement là où une mesure l'exige) ;
- sondes de la page : l'état du son vu par la page de scène, par le cadre (éléments `<audio>` de Remotion : en pause, muets, position),
  le plein écran, la surimpression ;
- `content_box` : la boîte des pixels non noirs d'une capture PNG (format de l'image affichée, bandes noires).

Ne lance ni n'arrête jamais le Jarvis vivant.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
from pathlib import Path
import struct
import subprocess
from typing import Any
import wave

from jarvis.adapters.remotion_compiler import shipped_engine_pin
from jarvis.domain.remotion_source import Composition
from tests.fakes.remotion_player_stack import RemotionStack
from tests.fakes.remotion_scene import scene_candidate
from tests.unit.presentation_playback_gate_world import _png_rows, harness

BASE = "/v1/presentation-studio/presentations"
AUDIO_TSX = """import React from "react";
import {AbsoluteFill, Audio, staticFile, useCurrentFrame} from "remotion";

export default function Scene(props: {title: string; bg: string}) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: props.bg}}>
      <Audio src={staticFile("tone.wav")} />
      <p id="label" style={{color: "#ffffff", fontSize: 48, margin: 24}}>{props.title}</p>
      <p id="frame" style={{color: "#ffffff", fontSize: 32, margin: 24}}>{String(frame)}</p>
    </AbsoluteFill>
  );
}
"""
SILENT_TSX = AUDIO_TSX.replace('      <Audio src={staticFile("tone.wav")} />\n', "").replace("Audio, staticFile, ", "")
PROPS = {"type": "object", "properties": {"title": {"type": "string", "default": "Scene", "max_length": 80},
                                          "bg": {"type": "color", "default": "#202060"}}}
#: (titre, largeur, hauteur, secondes, i/s, son, fond). Fonds saturés : une capture dit la scène et sa boîte.
MEDIA_DECK: list[tuple[str, int, int, int, int, bool, str]] = [
    ("A 16:9 son", 1920, 1080, 6, 30, True, "#b01010"),
    ("B 4:3 son", 1024, 768, 4, 30, True, "#10a010"),
    ("C 9:16", 720, 1280, 3, 30, False, "#1030c0"),
    ("D 1:1", 800, 800, 3, 30, False, "#c0a000"),
]
MEDIA_PREFABS = [f"presentation-studio.p0000000000b8.s{n:012d}" for n in range(1, len(MEDIA_DECK) + 1)]
MEDIA_SCENES = [f"pss_{n + 800:012d}" for n in range(1, len(MEDIA_DECK) + 1)]


def tone_wav(seconds: float = 6.0, rate: int = 22050, hz: float = 440.0) -> bytes:
    """Un WAV PCM 16 bits mono réel (RIFF....WAVE) : la note la, à mi-volume."""

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = int(seconds * rate)
        out.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * i / rate))) for i in range(frames)))
    return buffer.getvalue()


async def make_media_deck(stack: RemotionStack, *, title: str = "Media") -> tuple[str, str]:
    """Publie les quatre sources et crée la présentation (une partition qui les parcourt). Rend `(presentation_id, variant_id)`."""

    wav = tone_wav()
    for index, prefab_id in enumerate(MEDIA_PREFABS):
        name, width, height, seconds, fps, audio, bg = MEDIA_DECK[index]
        files: dict[str, Any] = {"src/Scene.tsx": AUDIO_TSX if audio else SILENT_TSX}
        if audio:
            files["public/tone.wav"] = wav
        await stack.core.prefabs.save(scene_candidate(
            prefab_id, engine=shipped_engine_pin(), title=name, composition=Composition("Scene", width, height, fps, seconds * fps),
            files=files, props=PROPS, sample={"props": {"title": name, "bg": bg}, "data": {}}), actor="user")
    scenes = [{"scene_id": MEDIA_SCENES[i], "prefab": {"id": MEDIA_PREFABS[i], "version": 1}, "title": MEDIA_DECK[i][0],
               "props": {"title": MEDIA_DECK[i][0], "bg": MEDIA_DECK[i][6]}, "data": {}} for i in range(len(MEDIA_DECK))]
    return await stack.presentation(scenes, title=title)


def drive_media(url: str, plan: list, *, timeout: int = 600, viewport: str = "1280x720", chrome_args: str = "") -> dict:
    from tests.unit.test_fullscreen_browser import _chrome
    driver = Path(__file__).parent / "_remotion_stage_browser.mjs"
    done = subprocess.run(["node", str(driver), url, _chrome(), json.dumps(plan)], capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, check=False, env={**os.environ, "CDP_VIEWPORT": viewport, "CDP_CHROME_ARGS": chrome_args})
    harness(done.returncode == 0, f"CDP driver exit {done.returncode}: {done.stderr[-2000:]}")
    return json.loads(done.stdout)


async def run_media(url: str, plan: list, **kwargs: Any) -> dict:
    return await asyncio.to_thread(drive_media, url, plan, **kwargs)


X = "#jvStudioExplorer"
FRAME = ("[...document.querySelectorAll('#jvStudioExplorer iframe[data-remotion-stage]')].find(x=>!x.classList.contains('sc-prefab-staged')"
         "&&x.style.visibility!=='hidden'&&x.getBoundingClientRect().width>0)")
SOUND_BTN = f"{X} [role=\"toolbar\"] [aria-label=\"Son\"]"
LIRE = f"{X} [role=\"toolbar\"] [data-act=\"continuous\"]"
FS_BTN = f"{X} .jvx-top-actions .jvx-btn"
#: What the page shows of the sound and of the Player on screen.
MEDIA = (f"(()=>{{const f={FRAME};let st=null;try{{st=f?f.contentWindow.__remotionStage.state():null}}catch(e){{}}"
         "const m=f?/\\.s0*(\\d+)(?:@|&|$)/.exec(decodeURIComponent(f.src||'')):null;"
         "const all=[...document.querySelectorAll('#jvStudioExplorer iframe[data-remotion-stage]')].map(x=>{let s=null;try{s=x.contentWindow.__remotionStage.state()}catch(e){}"
         "return {staged:x.classList.contains('sc-prefab-staged'),wanted:s&&s.soundWanted,muted:s&&s.muted,phase:s&&s.phase}});"
         "const b=document.querySelector('#jvStudioExplorer [role=\"toolbar\"] [aria-label=\"Son\"]');const pill=document.querySelector('#jvStudioExplorer .jvx-stage-sound');"
         "const v=JarvisStudioExplorer.playback.view();"
         "return {scene:m?'S'+m[1]:null,frame:st&&st.frame,playing:st&&st.playing,duration:st&&st.duration,wanted:st&&st.soundWanted,muted:st&&st.muted,"
         "blocked:st&&st.soundBlocked,keysRelayed:st&&st.keysRelayed,keysRefused:st&&st.keysRefused,frames:all,"
         "button:b?{pressed:b.getAttribute('aria-pressed'),title:b.title,state:b.getAttribute('data-sound')}:null,"
         "pill:pill&&!pill.hidden?pill.textContent:'',sound:JarvisStudioExplorer.playback.sound(),phase:v.phase,f:v.frame,"
         "notice:(JarvisStudioExplorer.state().notice||{}).text||''}})()")
#: In the sandbox of the scene on screen: Remotion's `<audio>` elements carrying the asset (paused, muted, position in seconds).
#: In a sandbox (`scope: sandbox` / `sandboxes`): the frame the scene drew (`#frame`, its own `useCurrentFrame()`), its title, and Remotion's
#: `<audio>` element for the asset (paused, muted, position in seconds), read in ONE evaluation so the frame and the audio time are the same
#: instant.
AUDIO_TAGS = ("(()=>{const fr=document.querySelector('#frame');const lb=document.querySelector('#label');"
              "const a=[...document.querySelectorAll('audio')].find(x=>String(x.currentSrc||x.src||'').includes('tone.wav'));"
              "return {frame:fr?+fr.textContent:null,title:lb?lb.textContent:null,"
              "audio:a?{paused:a.paused,muted:a.muted,volume:a.volume,t:Math.round(a.currentTime*1000)/1000}:null}})()")
FULLSCREEN = ("(()=>{const fs=document.fullscreenElement;const x=document.querySelector('#jvStudioExplorer');const th=x.querySelector('.jvx-theater');"
              "const r=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)]};"
              "const note=th.querySelector('.jvx-stage-note');const cs=getComputedStyle(note);"
              "return {element:fs?(fs===th?'stage':fs===x?'workspace':fs.tagName):null,mode:JarvisStudioExplorer.state().mode,"
              "tree:!!fs&&fs.contains(x.querySelector('.jvx-treepane')),meta:!!fs&&fs.contains(x.querySelector('.jvx-meta')),"
              "actions:!!fs&&fs.contains(x.querySelector('.jvx-actions')),strip:!!fs&&fs.contains(x.querySelector('.jvx-strip')),"
              "stage:r(th.querySelector('.jvx-stage')),frame:r(th.querySelector('iframe[data-remotion-stage]:not(.sc-prefab-staged)')),viewport:[innerWidth,innerHeight],"
              "chrome:th.getAttribute('data-chrome')||'shown',noteOpacity:cs.opacity,noteTransition:cs.transitionDuration,"
              "focus:document.activeElement?(document.activeElement.getAttribute('aria-label')||document.activeElement.className||document.activeElement.tagName):null,"
              "animations:document.getAnimations().length}})()")


def content_box(path: Path, *, threshold: int = 24) -> dict:
    """The box of the non-black pixels of a PNG capture: where the slide is drawn, the rest being the black letterbox bars."""

    width, height, channels, rows = _png_rows(path)
    left, top, right, bottom = width, height, -1, -1
    for y, row in enumerate(rows):
        for x in range(width):
            px = row[x * channels:x * channels + 3]
            if max(px) > threshold:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                bottom = y
    if right < 0:
        return {"width": width, "height": height, "box": None, "ratio": None}
    w, h = right - left + 1, bottom - top + 1
    return {"width": width, "height": height, "box": [left, top, w, h], "ratio": round(w / h, 3)}
