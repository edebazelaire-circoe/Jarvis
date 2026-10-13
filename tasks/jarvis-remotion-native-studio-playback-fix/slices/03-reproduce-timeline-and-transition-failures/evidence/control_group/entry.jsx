// Control group (Slice 03): the same kind of scene in a plain @remotion/player, no Jarvis wrapper (no sandbox, no stage page, no host, no
// follower). Bundled with the esbuild of the pinned Remotion runtime by build_and_run.mjs. Records what the Player itself does.
import React from "react";
import {createRoot} from "react-dom/client";
import {Player} from "@remotion/player";
import {AbsoluteFill, useCurrentFrame} from "remotion";

const Scene = () => {
  const frame = useCurrentFrame();
  return React.createElement(AbsoluteFill, {style: {background: "#b01010", color: "#fff", fontSize: 40}}, String(frame));
};

const log = [];
const t0 = performance.now();
const T = () => Math.round(performance.now() - t0);
window.__ctl = {log, players: {}, frames: () => Object.fromEntries(Object.entries(window.__ctl.players).map(([k, p]) => [k, p.getCurrentFrame()]))};

function mount(id, loop, extra) {
  const host = document.createElement("div");
  host.style.cssText = "width:320px;height:180px";
  document.body.appendChild(host);
  const ref = React.createRef();
  createRoot(host).render(React.createElement(Player, {
    ref, component: Scene, durationInFrames: 90, fps: 30, compositionWidth: 1280, compositionHeight: 720, loop,
    controls: false, initiallyMuted: true, style: {width: "100%", height: "100%"}, ...(extra || {})}));
  const wait = () => new Promise((ok) => {
    const poll = () => (ref.current ? ok(ref.current) : setTimeout(poll, 20));
    poll();
  });
  return wait().then((player) => {
    player.addEventListener("frameupdate", (e) => log.push([T(), id, "frame", e.detail.frame]));
    for (const name of ["play", "pause", "ended", "seeked"]) player.addEventListener(name, () => log.push([T(), id, name, player.getCurrentFrame()]));
    window.__ctl.players[id] = player;
    return player;
  });
}

window.__ctl.run = async () => {
  const once = await mount("loop_false", false);
  const looping = await mount("loop_true", true);
  const scrubbed = await mount("loop_false_seek", false);
  const holding = await mount("loop_false_hold", false, {moveToBeginningWhenEnded: false});
  once.play();
  looping.play();
  scrubbed.play();
  holding.play();
  setTimeout(() => scrubbed.seekTo(60), 1000);   // a user scrub forward while playing
  return true;
};
