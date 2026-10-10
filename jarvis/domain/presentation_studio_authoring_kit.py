"""The small module Core adds to every Remotion source the authoring planner generates (jarvis-remotion-presentation-integration, Slice 15).

`src/jarvis-kit.ts` turns the art direction's MOTION into frames. The theme prop carries the tokens (`enter_ms`, `stagger_ms`, `easing`,
`transition`); a scene that imports the kit animates the way the direction says without re-deriving it, so every scene of a deck and every
candidate of an exploratory request moves coherently and differently. It is plain TypeScript over `remotion` and `react` types only (no
network, no realm access: the Slice 06 static guards read it like any other module), it is fixed text (so a source id depends on it
only through the version below) and it is excluded from the gate's reading of the author's code (`presentation_studio_authoring_tsx.py`).

The brain may import it or ignore it; it may not provide a module of the same path (Core owns it).
"""

from __future__ import annotations

KIT_NAME = "jarvis-kit"
KIT_PATH = f"src/{KIT_NAME}.ts"
#: Bump when `KIT_SOURCE` changes: a new text is a new content, hence a new id for the same author source.
KIT_VERSION = 1

KIT_SOURCE = '''// Added by Jarvis (kit v1). Fixed text: read it, import it, do not edit it. Motion of the art direction as frames.
import {Easing, interpolate} from "remotion";
import type {CSSProperties} from "react";

export type Theme = {
  background: string; text: string; accent: string; muted: string; body: string; surface: string;
  font_heading: string; font_body: string; heading_weight: number; body_weight: number;
  radius: number; gap: number; scale: number; enter_ms: number; stagger_ms: number; easing: string; transition: string;
};

const CURVES: Record<string, (t: number) => number> = {
  linear: (t) => t,
  ease_out: Easing.out(Easing.cubic),
  ease_in_out: Easing.inOut(Easing.cubic),
  standard: Easing.bezier(0.2, 0, 0, 1),
  emphasized: Easing.bezier(0.3, 0, 0, 1.15),
  snappy: Easing.bezier(0.2, 0.9, 0.3, 1),
};

// 0 -> 1 over the direction's enter time, shifted by its stagger for the n-th element (index 0, 1, 2...). Clamped on both sides.
export function progress(frame: number, fps: number, theme: Theme, index = 0): number {
  const start = (theme.stagger_ms * index / 1000) * fps;
  const length = Math.max(1, (theme.enter_ms / 1000) * fps);
  return interpolate(frame, [start, start + length], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: CURVES[theme.easing] ?? CURVES.ease_out,
  });
}

// The direction's transition as a style for an element entering with progress p: fade, slide, scale or wipe (none: shown at once).
export function enterStyle(p: number, theme: Theme): CSSProperties {
  switch (theme.transition) {
    case "none": return {};
    case "slide": return {opacity: p, transform: `translateY(${(1 - p) * 32}px)`};
    case "scale": return {opacity: p, transform: `scale(${0.92 + 0.08 * p})`};
    case "wipe": return {clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`};
    default: return {opacity: p};
  }
}

// Sizes follow the direction's text scale and spacing: size(72) is a 72 px title at scale 1.
export function size(px: number, theme: Theme): number {
  return Math.round(px * theme.scale);
}
'''

__all__ = ["KIT_NAME", "KIT_PATH", "KIT_SOURCE", "KIT_VERSION"]
