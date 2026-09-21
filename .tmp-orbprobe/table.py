#!/usr/bin/env python3
"""Aplatit les res-*.json en un tableau lisible."""
import glob
import json
import sys
from pathlib import Path

pat = sys.argv[1] if len(sys.argv) > 1 else "res-*.json"
ROOT = Path(__file__).resolve().parent
rows = []
for f in sorted(glob.glob(str(ROOT / pat))):
    d = json.load(open(f))
    p = d.get("pixels")
    sb = d.get("server_state_before", {})
    sa = d.get("server_state_after", {})
    if not p:
        rows.append((Path(f).stem, "PAS DE PIXELS " + str(d.get("pixels_error"))))
        continue
    r, g, b = p["mean_rgb"]
    nr, ng, nbl = p["mean_rgb_nonblack"]
    rows.append((Path(f).stem,
                 "bus=%-9s srv=%-9s/%-9s lvl=%-6s | mean RGB %6.2f %6.2f %6.2f"
                 " | luma %6.2f | nonblack %5.1f%% | nbRGB %6.2f %6.2f %6.2f"
                 " | nbLuma %6.2f | sat %.3f | hue %3s"
                 % (d["bus_state_written"] + ("+w" if d["wave_fed"] else ""),
                    sb.get("state"), sa.get("state"), sb.get("level"),
                    r, g, b, p["mean_luma"], 100 * p["nonblack_frac"],
                    nr, ng, nbl, p["mean_luma_nonblack"],
                    p["mean_sat_nonblack"], p["dominant_hue_bin_deg"])))
w = max(len(a) for a, _ in rows)
for a, t in rows:
    print(a.ljust(w), t)
