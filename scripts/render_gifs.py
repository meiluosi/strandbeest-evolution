"""Render README/blog GIFs from exported Jansen poses.  Usage: python3 scripts/render_gifs.py [poses.json] [outdir]"""
import json, math, sys
from PIL import Image, ImageDraw

src = sys.argv[1] if len(sys.argv) > 1 else "docs/assets/jansen-poses.json"
outdir = sys.argv[2] if len(sys.argv) > 2 else "docs/assets"
d = json.load(open(src))
poses, foot, pivot = d["poses"], d["foot"], d["pivot"]
N = len(poses)
LINKS = [("P", "C"), ("G", "K"), ("K", "C"), ("G", "L"), ("K", "L"), ("G", "M"),
         ("C", "M"), ("L", "N"), ("M", "N"), ("M", "F"), ("N", "F")]
BG, FG, ACC, GRID = (250, 248, 244), (40, 40, 48), (229, 115, 63), (200, 196, 190)
SS = 2  # supersample for smoother lines

def new(w, h):
    im = Image.new("RGB", (w * SS, h * SS), BG)
    return im, ImageDraw.Draw(im)

def finish(im, w, h):
    return im.resize((w, h), Image.LANCZOS)

def single_leg():
    W, H = 480, 400
    s = 2.3
    ox, oy = 250, 95
    X = lambda p: (ox + p[0] * s) * SS
    Y = lambda p: (oy - p[1] * s) * SS
    frames = []
    low = min(p["y"] for p in foot)
    for k in range(N):
        im, dr = new(W, H)
        gy = (oy - low * s) * SS
        dr.line([(0, gy), (W * SS, gy)], fill=GRID, width=2 * SS)
        pts = [(X((p["x"], p["y"])), Y((p["x"], p["y"]))) for p in foot]
        dr.line(pts + [pts[0]], fill=ACC, width=3 * SS)
        P = {kk: (v["x"], v["y"]) for kk, v in poses[k].items()}
        P["P"] = (pivot["x"], pivot["y"])
        for a, b in LINKS:
            dr.line([(X(P[a]), Y(P[a])), (X(P[b]), Y(P[b]))], fill=FG, width=3 * SS)
        for name, p in P.items():
            r = (7 if name == "F" else 5) * SS
            c = ACC if name == "F" else (140, 140, 140) if name in "GP" else FG
            dr.ellipse([X(p) - r, Y(p) - r, X(p) + r, Y(p) + r], fill=c)
        frames.append(finish(im, W, H))
    return frames

def walker(legs=8):
    """Several legs with evenly spaced phases; stance feet stay put in the world, the body glides."""
    W, H = 640, 300
    s = 2.4
    # crank turns so that the stance foot moves backward: iterate theta downwards
    shift = [round(N * i / legs) for i in range(legs)]
    def feet(k):
        return [foot[(k + sh) % N] for sh in shift]
    # hip height / body x per frame from the contact feet
    X, Hh = [0.0], []
    order = [(-j) % N for j in range(N * 3)]
    xs, hs = [], []
    x = 0.0
    prev = None
    for j, k in enumerate(order):
        fs = feet(k)
        low = min(p["y"] for p in fs)
        contact = [p for p in fs if p["y"] <= low + 1.0]
        mx = sum(p["x"] for p in contact) / len(contact)
        if prev is not None:
            x += -(mx - prev) if abs(mx - prev) < 50 else 0.0
        # use per-foot tracking: advance by the mean displacement of contact feet between consecutive frames
        prev_feet = feet(order[j - 1]) if j else None
        if prev_feet:
            disp = [-(a["x"] - b["x"]) for a, b in zip(fs, prev_feet) if a["y"] <= low + 1.0 and b["y"] <= low + 1.0]
            x_step = sum(disp) / len(disp) if disp else 0.0
            x = xs[-1] + x_step
        else:
            x = 0.0
        xs.append(x); hs.append(-low); prev = mx
    frames = []
    for j in range(N):
        j2 = j + N  # use the middle cycle so the loop is seamless in motion
        k = order[j2]
        im, dr = new(W, H)
        bx, hh = xs[j2] - xs[N], hs[j2]
        cx = W * 0.5
        gy = (H - 40) * SS
        base = H - 40
        ground_y = base
        hip_y = ground_y - hh * s
        # ground ticks scroll with the world
        for t in range(-20, 40):
            gx = (cx + (t * 40 - bx) * s) * SS
            dr.line([(gx, gy), (gx - 10 * SS, gy + 12 * SS)], fill=GRID, width=2 * SS)
        dr.line([(0, gy), (W * SS, gy)], fill=FG, width=2 * SS)
        fs = feet(k)
        # body bar
        dr.rounded_rectangle([(cx - 120 * 1) * SS, (hip_y - 14) * SS, (cx + 120) * SS, (hip_y + 4) * SS], radius=8 * SS, fill=FG)
        for i, f in enumerate(fs):
            fx = cx + f["x"] * s
            fy = hip_y - f["y"] * s
            hx = cx + ((i - (legs - 1) / 2) * (240 / legs)) 
            dr.line([(hx * SS, hip_y * SS), (fx * SS, fy * SS)], fill=ACC if f["y"] <= -hh + 1.0 else (120, 120, 130), width=3 * SS)
            r = 4 * SS
            dr.ellipse([fx * SS - r, fy * SS - r, fx * SS + r, fy * SS + r], fill=FG)
        frames.append(finish(im, W, H))
    return frames

def save(frames, path, ms=40):
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0, optimize=True)
    print(path, len(frames))

save(single_leg(), f"{outdir}/jansen-leg.gif")
save(walker(), f"{outdir}/walker.gif")
