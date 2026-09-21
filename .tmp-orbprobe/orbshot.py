#!/usr/bin/env python3
"""orbshot.py -- banc de mesure PIXEL de l'orbe ai-visualizer.

Pilote le faux bus, tire une capture headless Chrome de la face, et sort
des NOMBRES: couleur moyenne, couleur moyenne des pixels non-noirs,
luminosite, saturation, histogramme de teinte.

  python orbshot.py idle
  python orbshot.py speaking --wave
  python orbshot.py thinking --face radial --label t2

Imprime un objet JSON sur stdout.
"""
import argparse
import json
import math
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUS = ROOT / "bus"
SHOTS = ROOT / "shots"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
STATES = ("idle", "listening", "thinking", "speaking")


# ---------------------------------------------------------------- bus
def write_state(state):
    BUS.mkdir(parents=True, exist_ok=True)
    tmp = BUS / ".voice_state.tmp"
    tmp.write_text(state + "\n", encoding="utf-8")
    os.replace(tmp, BUS / ".voice_state")


def make_samples(t):
    return [(math.sin(i * 0.55 + t * 9.0) * 0.6
             + math.sin(i * 1.7 - t * 13.0) * 0.4) * 9000.0
            * (0.35 + 0.65 * abs(math.sin(t * 2.6)))
            for i in range(64)]


def write_waveform():
    """Une waveform DATEE MAINTENANT. Le serveur ne la juge fraiche que
    moins de 0.6 s: il faut donc la reecrire en boucle pendant le tir."""
    t = time.time()
    payload = json.dumps({"ts": t, "samples": make_samples(t)})
    tmp = BUS / ".voice_waveform.tmp"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, BUS / ".voice_waveform")


def clear_waveform():
    for n in (".voice_waveform", ".voice_waveform.tmp"):
        try:
            (BUS / n).unlink()
        except OSError:
            pass


class WaveFeeder(threading.Thread):
    """Rejoue une waveform fraiche toutes les 200 ms tant que le tir dure."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_evt = threading.Event()

    def run(self):
        while not self.stop_evt.is_set():
            write_waveform()
            self.stop_evt.wait(0.2)


# ------------------------------------------------------------- server
def get_state(port, timeout=3.0):
    url = "http://127.0.0.1:%d/state" % port
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, e)}
    s = d.get("samples") or []
    peak = max((abs(float(x)) for x in s), default=0.0)
    return {"state": d.get("state"),
            "level": round(float(d.get("level", 0)), 4),
            "samples_peak": round(peak, 1),
            "loading": d.get("loading"), "alert": d.get("alert")}


# ------------------------------------------------------------- chrome
def shoot(url, png, size, vtb, profile):
    cmd = [CHROME, "--headless=new", "--disable-gpu",
           "--screenshot=" + png,
           "--window-size=%d,%d" % (size, size),
           "--virtual-time-budget=%d" % vtb,
           "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions",
           "--force-device-scale-factor=1",
           "--user-data-dir=" + profile, url]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    return {"rc": p.returncode, "secs": round(time.time() - t0, 2),
            "stderr_tail": p.stderr.decode(errors="replace")[-300:]}


# ------------------------------------------------------------ analyse
def load_pixels(png):
    """-> (w, h, bytes RGB, decodeur). Pillow si dispo, sinon zlib maison."""
    try:
        from PIL import Image
        im = Image.open(png).convert("RGB")
        return im.width, im.height, im.tobytes(), "pillow"
    except ImportError:
        pass
    import zlib
    raw = Path(png).read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "pas un PNG"
    pos = 8
    idat = bytearray()
    w = h = bd = ct = il = 0
    while pos < len(raw):
        ln = int.from_bytes(raw[pos:pos + 4], "big")
        typ = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w = int.from_bytes(data[0:4], "big")
            h = int.from_bytes(data[4:8], "big")
            bd, ct, il = data[8], data[9], data[12]
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
        pos += 12 + ln
    assert bd == 8 and il == 0, "bitdepth=%d interlace=%d non geres" % (bd, il)
    nch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
    stride = w * nch
    dec = zlib.decompress(bytes(idat))
    out = bytearray(stride * h)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = dec[p]
        p += 1
        line = bytearray(dec[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(nch, stride):
                line[i] = (line[i] + line[i - nch]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                c = prev[i - nch] if i >= nch else 0
                b = prev[i]
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if nch == 3:
        return w, h, bytes(out), "zlib"
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        if nch == 4:
            rgb[3 * i:3 * i + 3] = out[4 * i:4 * i + 3]
        elif nch == 1:
            v = out[i]
            rgb[3 * i:3 * i + 3] = bytes((v, v, v))
        else:
            v = out[2 * i]
            rgb[3 * i:3 * i + 3] = bytes((v, v, v))
    return w, h, bytes(rgb), "zlib"


def tiles_luma(w, h, rgb, grid=4, step=2):
    """Grille grid x grid de luminances moyennes: une SIGNATURE spatiale.
    Deux etats qui bougent la meme quantite de lumiere mais pas au meme
    endroit se separent ici alors que la moyenne globale les confond."""
    acc = [[0.0] * grid for _ in range(grid)]
    cnt = [[0] * grid for _ in range(grid)]
    for y in range(0, h, step):
        ty = min(grid - 1, y * grid // h)
        base = y * w * 3
        for x in range(0, w, step):
            tx = min(grid - 1, x * grid // w)
            i = base + x * 3
            acc[ty][tx] += (0.2126 * rgb[i] + 0.7152 * rgb[i + 1]
                            + 0.0722 * rgb[i + 2])
            cnt[ty][tx] += 1
    return [[round(acc[r][c] / cnt[r][c], 2) if cnt[r][c] else None
             for c in range(grid)] for r in range(grid)]


def crop_stats(w, h, rgb, box, black=12):
    """Mesure d'une fenetre x,y,w,h en pixels: l'encre d'un HUD."""
    cx, cy, cw, ch = box
    cx = max(0, min(w - 1, cx))
    cy = max(0, min(h - 1, cy))
    cw = max(1, min(w - cx, cw))
    ch = max(1, min(h - cy, ch))
    n = nn = 0
    lum = 0.0
    sr = sg = sb = 0
    for y in range(cy, cy + ch):
        base = y * w * 3
        for x in range(cx, cx + cw):
            i = base + x * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            n += 1
            sr += r
            sg += g
            sb += b
            lu = 0.2126 * r + 0.7152 * g + 0.0722 * b
            lum += lu
            if lu > black:
                nn += 1
    return {"box": [cx, cy, cw, ch], "px": n,
            "mean_luma": round(lum / n, 3),
            "ink_frac": round(nn / n, 4),
            "mean_rgb": [round(sr / n, 2), round(sg / n, 2), round(sb / n, 2)]}


def analyse(png, step=2, black=12, grid=4, crops=None):
    w, h, rgb, how = load_pixels(png)
    sr = sg = sb = 0
    nr = ng = nb = 0
    n = nn = 0
    lum = 0.0
    lum_nb = 0.0
    sat_nb = 0.0
    hue = [0.0] * 12
    for y in range(0, h, step):
        base = y * w * 3
        for x in range(0, w, step):
            i = base + x * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            n += 1
            sr += r
            sg += g
            sb += b
            lu = 0.2126 * r + 0.7152 * g + 0.0722 * b
            lum += lu
            if lu > black:
                nn += 1
                nr += r
                ng += g
                nb += b
                lum_nb += lu
                mx = max(r, g, b)
                mn = min(r, g, b)
                d = mx - mn
                sat_nb += (d / mx) if mx else 0.0
                if d:
                    if mx == r:
                        hh = (60.0 * ((g - b) / d) + 360.0) % 360.0
                    elif mx == g:
                        hh = 60.0 * ((b - r) / d) + 120.0
                    else:
                        hh = 60.0 * ((r - g) / d) + 240.0
                    hue[int(hh // 30) % 12] += d / 255.0
    tot = sum(hue) or 1.0
    res = {"decoder": how, "w": w, "h": h, "sampled_px": n, "step": step,
           "mean_rgb": [round(sr / n, 2), round(sg / n, 2), round(sb / n, 2)],
           "mean_luma": round(lum / n, 2),
           "nonblack_frac": round(nn / n, 4),
           "hue_hist_12": [round(v / tot, 4) for v in hue]}
    if nn:
        res["mean_rgb_nonblack"] = [round(nr / nn, 2), round(ng / nn, 2),
                                    round(nb / nn, 2)]
        res["mean_luma_nonblack"] = round(lum_nb / nn, 2)
        res["mean_sat_nonblack"] = round(sat_nb / nn, 4)
        res["dominant_hue_bin_deg"] = hue.index(max(hue)) * 30
    else:
        res["mean_rgb_nonblack"] = None
        res["mean_luma_nonblack"] = None
        res["mean_sat_nonblack"] = None
        res["dominant_hue_bin_deg"] = None
    if grid:
        res["tiles_luma_%dx%d" % (grid, grid)] = tiles_luma(w, h, rgb,
                                                            grid, step)
    if crops:
        res["crops"] = {k: crop_stats(w, h, rgb, v, black)
                        for k, v in crops.items()}
    return res


# --------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state", choices=STATES)
    ap.add_argument("--wave", action="store_true",
                    help="alimente aussi .voice_waveform en continu")
    ap.add_argument("--face", default="board")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--vtb", type=int, default=4000)
    ap.add_argument("--settle", type=float, default=0.4)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--grid", type=int, default=4,
                    help="signature spatiale NxN (0 = aucune)")
    ap.add_argument("--crop", action="append", default=[],
                    help="nom=x,y,w,h -- mesure d'une fenetre (repetable)")
    ap.add_argument("--keep-bus", action="store_true")
    a = ap.parse_args()

    SHOTS.mkdir(parents=True, exist_ok=True)
    tag = a.label or time.strftime("%H%M%S")
    name = "%s-%s%s-%s.png" % (a.face, a.state, "-wave" if a.wave else "", tag)
    png = Path(a.out) if a.out else SHOTS / name
    url = "http://127.0.0.1:%d/faces/%s/" % (a.port, a.face)

    write_state(a.state)
    feeder = None
    if a.wave:
        write_waveform()
        feeder = WaveFeeder()
        feeder.start()
    else:
        clear_waveform()
    time.sleep(a.settle)

    st_before = get_state(a.port)
    profile = ROOT / "chrome-profile"
    sh = shoot(url, str(png), a.size, a.vtb, str(profile))
    st_after = get_state(a.port)
    if feeder:
        feeder.stop_evt.set()
        feeder.join(timeout=1)
    if a.wave and not a.keep_bus:
        clear_waveform()

    res = {"label": tag, "face": a.face, "url": url,
           "bus_state_written": a.state, "wave_fed": a.wave,
           "server_state_before": st_before, "server_state_after": st_after,
           "chrome": sh, "png": str(png)}
    if sh["rc"] == 0 and png.exists():
        res["png_bytes"] = png.stat().st_size
        crops = {}
        for spec in a.crop:
            name, _, nums = spec.partition("=")
            crops[name] = [int(v) for v in nums.split(",")]
        try:
            res["pixels"] = analyse(str(png), step=a.step, grid=a.grid,
                                    crops=crops or None)
        except Exception as e:
            res["pixels_error"] = "%s: %s" % (type(e).__name__, e)
    else:
        res["pixels_error"] = "pas de PNG"
    print(json.dumps(res))


if __name__ == "__main__":
    main()
