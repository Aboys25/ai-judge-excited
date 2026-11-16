#!/usr/bin/env python3
"""Draw one exciting image: a brass padlock cracking open, spilling cosmos.

A large padlock hangs tilted in deep indigo dark, its shackle swung half
open. From a glowing crack that runs from the empty socket to the body's
edge, a ribbon of starlit blue-violet space pours out, sweeping an S-curve
down to a glowing pool. The crack is the only light source: warm rim-light
on the brass, cold light in the spill. Pure standard library, and fully
deterministic (fixed arithmetic, fixed-seed generators).
"""

import math
import os
import struct
import zlib

W = H = 1024


# ------------------------------------------------------------------- rng ---
class Rng:
    """Xorshift32 with a fixed seed: identical output on every run."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF or 1

    def __call__(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s & 0xFFFFFFFF
        return self.s / 4294967296.0


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t + 0.5) for i in range(3))


# ------------------------------------------------------------- transform ---
# The padlock is designed in local coordinates, rotated so its top leans
# left, then placed in the frame.
TILT = math.radians(-25.0)
CT, ST = math.cos(TILT), math.sin(TILT)
TX, TY = 430.0, 420.0


def xf(x, y):
    return (TX + x * CT - y * ST, TY + x * ST + y * CT)


def xfs(pts):
    return [xf(x, y) for x, y in pts]


# The shackle swings open about its left leg.
PIV = (-127.0, -40.0)
SWING = math.radians(-32.0)
CS, SS = math.cos(SWING), math.sin(SWING)


def swing(x, y):
    dx, dy = x - PIV[0], y - PIV[1]
    return (PIV[0] + dx * CS - dy * SS, PIV[1] + dx * SS + dy * CS)


def swing_xf(pts):
    return [xf(*swing(x, y)) for x, y in pts]


EXIT = xf(220.0, 98.0)          # crack mouth on the body edge / ribbon start
POOL_C = (815.0, 900.0)         # where the spilled cosmos pools


# -------------------------------------------------------------- palette ---
def _palette():
    stops = [
        (0, (4, 5, 14)),
        (60, (10, 12, 34)),
        (120, (24, 22, 64)),
        (180, (52, 38, 110)),
        (230, (100, 70, 170)),
        (255, (170, 150, 235)),
    ]
    out = []
    for i in range(256):
        for k in range(len(stops) - 1):
            e0, c0 = stops[k]
            e1, c1 = stops[k + 1]
            if e0 <= i <= e1:
                t = 0.0 if e1 == e0 else (i - e0) / (e1 - e0)
                out.append(bytes(_mix(c0, c1, t)))
                break
    return out


PAL = _palette()


def _radial(peak, sigma):
    """Gaussian falloff over squared-distance buckets (bucket = r^2 >> 12)."""
    n = ((W * W + H * H) >> 12) + 2
    inv = 1.0 / (2.0 * sigma * sigma)
    return [peak * math.exp(-((b << 12) * inv)) for b in range(n)]


# ----------------------------------------------------------- framebuffer ---
def build_background():
    """Vertical gradient + glow around the pool and the crack + vignette."""
    pool_lut = _radial(72.0, 260.0)
    crack_lut = _radial(58.0, 200.0)
    px, py = POOL_C
    cx, cy = EXIT
    dxp2 = [int((x - px) ** 2) for x in range(W)]
    dxc2 = [int((x - cx) ** 2) for x in range(W)]
    rows = []
    for y in range(H):
        base = 6.0 + 20.0 * (y / H)
        dyp2 = int((y - py) ** 2)
        dyc2 = int((y - cy) ** 2)
        ey = y if y < H - 1 - y else H - 1 - y
        cells = []
        for x in range(W):
            e = (base + pool_lut[(dxp2[x] + dyp2) >> 12]
                 + crack_lut[(dxc2[x] + dyc2) >> 12])
            ex = x if x < W - 1 - x else W - 1 - x
            d = ex if ex < ey else ey
            if d < 80:
                e -= (80 - d) * 0.10
            if e < 0:
                e = 0
            elif e > 255:
                e = 255
            cells.append(PAL[int(e)])
        rows.append(bytearray(b"".join(cells)))
    return rows


# --------------------------------------------------------------- raster ---
def span(row, x0f, x1f, rgb, alpha, add):
    """Blend one horizontal span [x0f, x1f) with fractional edge coverage."""
    if x1f <= 0.0 or x0f >= W:
        return
    x0 = int(x0f)
    if x0 < 0:
        x0 = 0
    x1 = int(x1f) + 1
    if x1 > W:
        x1 = W
    r, g, b = rgb
    if add:
        for x in range(x0, x1):
            lo = x * 1.0 if x * 1.0 > x0f else x0f
            hi = x + 1.0 if x + 1.0 < x1f else x1f
            cov = hi - lo
            if cov <= 0.0:
                continue
            a = alpha * (cov if cov < 1.0 else 1.0)
            i = x * 3
            v = row[i] + int(r * a)
            row[i] = 255 if v > 255 else v
            v = row[i + 1] + int(g * a)
            row[i + 1] = 255 if v > 255 else v
            v = row[i + 2] + int(b * a)
            row[i + 2] = 255 if v > 255 else v
    else:
        for x in range(x0, x1):
            lo = x * 1.0 if x * 1.0 > x0f else x0f
            hi = x + 1.0 if x + 1.0 < x1f else x1f
            cov = hi - lo
            if cov <= 0.0:
                continue
            a = alpha * (cov if cov < 1.0 else 1.0)
            ia = 1.0 - a
            i = x * 3
            row[i] = int(row[i] * ia + r * a + 0.5)
            row[i + 1] = int(row[i + 1] * ia + g * a + 0.5)
            row[i + 2] = int(row[i + 2] * ia + b * a + 0.5)


def poly(rows, pts, rgb, alpha=1.0, add=False):
    """Scanline polygon fill with fractional edge coverage."""
    ys = [p[1] for p in pts]
    y0 = int(min(ys))
    if y0 < 0:
        y0 = 0
    y1 = int(max(ys)) + 1
    if y1 > H - 1:
        y1 = H - 1
    n = len(pts)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            if (ay <= yc < by) or (by <= yc < ay):
                xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
        xs.sort()
        row = rows[y]
        for k in range(0, len(xs) - 1, 2):
            span(row, xs[k], xs[k + 1], rgb, alpha, add)


def seg(rows, x0, y0, x1, y1, width, rgb, alpha=1.0, add=False):
    """A thick line segment, drawn as a quad."""
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    if ln < 1e-9:
        return
    nx, ny = -dy / ln * width * 0.5, dx / ln * width * 0.5
    poly(rows, [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)],
         rgb, alpha, add)


def disc(rows, cx, cy, r, rgb, alpha, add=True):
    """Soft disc with a quadratic falloff."""
    y0 = int(cy - r)
    if y0 < 0:
        y0 = 0
    y1 = int(cy + r) + 1
    if y1 > H - 1:
        y1 = H - 1
    r2 = r * r
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        rem = r2 - dy * dy
        if rem <= 0:
            continue
        half = math.sqrt(rem)
        x0 = int(cx - half)
        if x0 < 0:
            x0 = 0
        x1 = int(cx + half) + 1
        if x1 > W:
            x1 = W
        row = rows[y]
        for x in range(x0, x1):
            dx = x + 0.5 - cx
            t = (dx * dx + dy * dy) / r2
            if t >= 1.0:
                continue
            a = alpha * (1.0 - t) * (1.0 - t)
            i = x * 3
            if add:
                v = row[i] + int(rgb[0] * a)
                row[i] = 255 if v > 255 else v
                v = row[i + 1] + int(rgb[1] * a)
                row[i + 1] = 255 if v > 255 else v
                v = row[i + 2] + int(rgb[2] * a)
                row[i + 2] = 255 if v > 255 else v
            else:
                ia = 1.0 - a
                row[i] = int(row[i] * ia + rgb[0] * a + 0.5)
                row[i + 1] = int(row[i + 1] * ia + rgb[1] * a + 0.5)
                row[i + 2] = int(row[i + 2] * ia + rgb[2] * a + 0.5)


def ellipse(rows, cx, cy, rx, ry, rgb, alpha=1.0, add=False):
    """Filled ellipse via scanline spans."""
    y0 = int(cy - ry)
    if y0 < 0:
        y0 = 0
    y1 = int(cy + ry) + 1
    if y1 > H - 1:
        y1 = H - 1
    for y in range(y0, y1 + 1):
        dy = (y + 0.5 - cy) / ry
        if abs(dy) >= 1.0:
            continue
        half = rx * math.sqrt(1.0 - dy * dy)
        span(rows[y], cx - half, cx + half, rgb, alpha, add)


def arc_line(rows, cx, cy, r, a0, a1, steps, width, rgb, alpha, add=False):
    """An arc stroke, built from short segments."""
    prev = None
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        p = (cx + r * math.cos(a), cy + r * math.sin(a))
        if prev is not None:
            seg(rows, prev[0], prev[1], p[0], p[1], width, rgb, alpha, add)
        prev = p


def stroke_ellipse(rows, cx, cy, rx, ry, steps, width, rgb, alpha, add=False):
    """An ellipse outline, built from short segments."""
    prev = None
    for i in range(steps + 1):
        a = 2.0 * math.pi * i / steps
        p = (cx + rx * math.cos(a), cy + ry * math.sin(a))
        if prev is not None:
            seg(rows, prev[0], prev[1], p[0], p[1], width, rgb, alpha, add)
        prev = p


def rounded_rect(x0, y0, x1, y1, r, steps=6):
    """Polygon for a rounded rectangle (angles sweep clockwise, y-down)."""
    pts = []
    for ccx, ccy, a0 in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0),
                         (x0 + r, y0 + r, 180.0), (x1 - r, y0 + r, 270.0)):
        for i in range(steps + 1):
            a = math.radians(a0 + 90.0 * i / steps)
            pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    return pts


def arc_band(cx, cy, r_out, r_in, a0, a1, steps=30):
    """Polygon for an annular band between two radii and two angles."""
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + r_out * math.cos(a), cy + r_out * math.sin(a)))
    for i in range(steps, -1, -1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + r_in * math.cos(a), cy + r_in * math.sin(a)))
    return pts


# ---------------------------------------------------------------- colors ---
BRASS = (118, 74, 30)
STEEL = (92, 102, 120)
STEEL_DARK = (40, 46, 58)
STEEL_LIGHT = (214, 226, 244)
RIM = (255, 176, 86)
WHITE = (255, 255, 255)


# ------------------------------------------------------------------ stars ---
def draw_stars(rows):
    rng = Rng(0xC0FFEE)
    for _ in range(80):
        x = int(rng() * W)
        y = int(rng() * H)
        b = 36 + int(rng() * 70)
        row = rows[y]
        i = x * 3
        row[i] = min(255, row[i] + b)
        row[i + 1] = min(255, row[i + 1] + b)
        row[i + 2] = min(255, row[i + 2] + min(255, b + 22))
        if rng() < 0.22 and x < W - 1 and y < H - 1:
            for dx, dy in ((1, 0), (0, 1), (1, 1)):
                r2 = rows[y + dy]
                j = (x + dx) * 3
                r2[j] = min(255, r2[j] + b // 2)
                r2[j + 1] = min(255, r2[j + 1] + b // 2)
                r2[j + 2] = min(255, r2[j + 2] + b // 2)


# --------------------------------------------------------------- padlock ---
def draw_padlock(rows):
    body = xfs(rounded_rect(-220, -75, 220, 255, 46))
    poly(rows, body, BRASS, 1.0)
    # Cool shadow mass on the far side, away from the crack's light.
    disc(rows, 190, 720, 330, (8, 8, 22), 0.38, add=False)
    # Warm light spilling from the crack onto the brass.
    disc(rows, EXIT[0], EXIT[1], 270, (255, 148, 58), 0.26)
    disc(rows, EXIT[0], EXIT[1], 120, (255, 192, 120), 0.30)
    # Lit top face.
    poly(rows, xfs([(-198, -75), (198, -75), (198, -44), (-198, -44)]),
         (255, 202, 132), 0.14)
    # Dark silhouette keyline.
    for i in range(len(body)):
        a, b = body[i], body[(i + 1) % len(body)]
        seg(rows, a[0], a[1], b[0], b[1], 3.0, (28, 15, 8), 0.9)
    # Rim light on the crack side: right edge and top-right edge.
    r0, r1 = xf(220, -75), xf(220, 255)
    seg(rows, r0[0], r0[1], r1[0], r1[1], 4.0, RIM, 0.85, add=True)
    t0, t1 = xf(30, -75), xf(220, -75)
    seg(rows, t0[0], t0[1], r1[0] * 0.0 + t1[0], t1[1], 3.5, RIM, 0.7, add=True)
    # Keyhole.
    kh = xf(-35, 85)
    disc(rows, kh[0], kh[1], 25, (14, 9, 6), 1.0, add=False)
    poly(rows, xfs([(-52, 100), (-18, 100), (-8, 172), (-62, 172)]),
         (14, 9, 6), 1.0)
    # Empty socket where the shackle's leg used to sit.
    soc = xf(127, -70)
    ellipse(rows, soc[0], soc[1], 26, 11, (18, 11, 7), 1.0)


def draw_shackle(rows):
    band = swing_xf(arc_band(0, -75, 150, 104, 180, 360, 34))
    poly(rows, band, STEEL, 1.0)
    leg_l = swing_xf([(-150, -78), (-104, -78), (-104, -18), (-150, -18)])
    leg_r = swing_xf([(104, -78), (150, -78), (150, -18), (104, -18)])
    poly(rows, leg_l, STEEL, 1.0)
    poly(rows, leg_r, STEEL, 1.0)
    # Outer rim highlight and inner shadow along the arc.
    outer = swing_xf([(150 * math.cos(math.radians(a)),
                       -75 + 150 * math.sin(math.radians(a)))
                      for a in range(180, 361, 6)])
    for i in range(len(outer) - 1):
        seg(rows, outer[i][0], outer[i][1], outer[i + 1][0], outer[i + 1][1],
            3.0, STEEL_LIGHT, 0.75)
    inner = swing_xf([(104 * math.cos(math.radians(a)),
                       -75 + 104 * math.sin(math.radians(a)))
                      for a in range(180, 361, 6)])
    for i in range(len(inner) - 1):
        seg(rows, inner[i][0], inner[i][1], inner[i + 1][0], inner[i + 1][1],
            3.0, STEEL_DARK, 0.9)
    # Rounded cap on the lifted leg's free end.
    cap = xf(*swing(127, -18))
    disc(rows, cap[0], cap[1], 23, STEEL, 1.0, add=False)
    disc(rows, cap[0] - 4, cap[1] - 4, 6, STEEL_LIGHT, 0.3)


# ---------------------------------------------------------------- ribbon ---
P1 = (920.0, 420.0)
P2 = (400.0, 740.0)
P3 = (820.0, 885.0)

RIBBON_STOPS = [
    (0.0, (252, 246, 255)),
    (0.25, (190, 165, 255)),
    (0.55, (120, 95, 245)),
    (0.85, (70, 75, 215)),
    (1.0, (58, 66, 205)),
]


def ribbon_color(t):
    for k in range(len(RIBBON_STOPS) - 1):
        t0, c0 = RIBBON_STOPS[k]
        t1, c1 = RIBBON_STOPS[k + 1]
        if t0 <= t <= t1:
            u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return _mix(c0, c1, u)
    return RIBBON_STOPS[-1][1]


def ribbon_width(t):
    return 14.0 + 74.0 * (t ** 0.65)


def ribbon_point(t):
    """Centre, unit normal, and half-width of the spill at parameter t."""
    u = 1.0 - t
    x = (u ** 3 * EXIT[0] + 3 * u * u * t * P1[0]
         + 3 * u * t * t * P2[0] + t ** 3 * P3[0])
    y = (u ** 3 * EXIT[1] + 3 * u * u * t * P1[1]
         + 3 * u * t * t * P2[1] + t ** 3 * P3[1])
    dx = (3 * u * u * (P1[0] - EXIT[0]) + 6 * u * t * (P2[0] - P1[0])
          + 3 * t * t * (P3[0] - P2[0]))
    dy = (3 * u * u * (P1[1] - EXIT[1]) + 6 * u * t * (P2[1] - P1[1])
          + 3 * t * t * (P3[1] - P2[1]))
    ln = math.hypot(dx, dy)
    return (x, y), (-dy / ln, dx / ln), ribbon_width(t) * 0.5


def draw_ribbon(rows):
    n = 56
    prev = None
    for i in range(n + 1):
        t = i / n
        cur = ribbon_point(t)
        if prev is not None:
            (x0, y0), (nx0, ny0), hw0 = prev
            (x1, y1), (nx1, ny1), hw1 = cur
            poly(rows, [(x0 - nx0 * hw0, y0 - ny0 * hw0),
                        (x0 + nx0 * hw0, y0 + ny0 * hw0),
                        (x1 + nx1 * hw1, y1 + ny1 * hw1),
                        (x1 - nx1 * hw1, y1 - ny1 * hw1)],
                 ribbon_color(t - 0.5 / n), 1.0)
        prev = cur
    # Bright core stream, fading quickly along the first half of the flow.
    for i in range(28):
        t0, t1 = i / 56.0, (i + 1) / 56.0
        c0 = ribbon_point(t0)[0]
        c1 = ribbon_point(t1)[0]
        seg(rows, c0[0], c0[1], c1[0], c1[1], 5.5 * (1.0 - t0 * 2.0),
            WHITE, 0.55 * (1.0 - t0 * 2.0), add=True)
    # One lit edge, one shaded edge.
    for i in range(n):
        t0, t1 = i / n, (i + 1) / n
        (x0, y0), (nx0, ny0), hw0 = ribbon_point(t0)
        (x1, y1), (nx1, ny1), hw1 = ribbon_point(t1)
        seg(rows, x0 + nx0 * hw0 * 0.92, y0 + ny0 * hw0 * 0.92,
            x1 + nx1 * hw1 * 0.92, y1 + ny1 * hw1 * 0.92,
            2.5, (222, 228, 255), 0.4, add=True)
        seg(rows, x0 - nx0 * hw0 * 0.92, y0 - ny0 * hw0 * 0.92,
            x1 - nx1 * hw1 * 0.92, y1 - ny1 * hw1 * 0.92,
            2.5, (30, 26, 90), 0.35)


def draw_spill_details(rows):
    rng = Rng(0x5EED1)
    for _ in range(110):
        t = 0.04 + 0.94 * rng()
        (x, y), (nx, ny), hw = ribbon_point(t)
        off = (rng() * 2.0 - 1.0) * hw * 0.72
        xi, yi = int(x + nx * off), int(y + ny * off)
        if not (0 <= xi < W and 0 <= yi < H):
            continue
        r = rng()
        if r < 0.62:
            row = rows[yi]
            j = xi * 3
            row[j] = min(255, row[j] + 120)
            row[j + 1] = min(255, row[j + 1] + 120)
            row[j + 2] = 255
        elif r < 0.9:
            if xi < W - 1 and yi < H - 1:
                for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    row = rows[yi + dy]
                    j = (xi + dx) * 3
                    row[j] = min(255, row[j] + 90)
                    row[j + 1] = min(255, row[j + 1] + 110)
                    row[j + 2] = 255
        else:
            if 3 <= xi < W - 3 and 3 <= yi < H - 3:
                for dx, dy, add in ((0, 0, 150), (-1, 0, 70), (1, 0, 70),
                                    (0, -1, 70), (0, 1, 70), (-2, 0, 35),
                                    (2, 0, 35), (0, -2, 35), (0, 2, 35)):
                    row = rows[yi + dy]
                    j = (xi + dx) * 3
                    row[j] = min(255, row[j] + add)
                    row[j + 1] = min(255, row[j + 1] + add)
                    row[j + 2] = 255
    # Small wave curls hugging the ribbon's edges.
    for t, side, rad in ((0.30, 1.0, 12.0), (0.52, -1.0, 13.0),
                         (0.74, 1.0, 12.0)):
        (x, y), (nx, ny), hw = ribbon_point(t)
        ccx, ccy = x + nx * hw * 0.85 * side, y + ny * hw * 0.85 * side
        ang = math.atan2(ny * side, nx * side)
        arc_line(rows, ccx, ccy, rad, ang - 1.15, ang + 1.15, 10, 2.5,
                 (226, 232, 255), 0.7, add=True)


def draw_pool(rows):
    disc(rows, POOL_C[0], POOL_C[1], 175, (66, 66, 195), 0.30)
    ellipse(rows, 815, 900, 115, 48, (58, 66, 205), 1.0)
    ellipse(rows, 800, 890, 78, 30, (88, 98, 235), 0.9)
    stroke_ellipse(rows, 815, 900, 115, 48, 40, 3.0, (168, 178, 255),
                   0.6, add=True)
    stroke_ellipse(rows, 815, 900, 142, 60, 44, 2.5, (140, 150, 235),
                   0.35, add=True)
    stroke_ellipse(rows, 815, 900, 172, 73, 48, 2.0, (110, 120, 220),
                   0.22, add=True)
    # Droplets thrown past the pool, shrinking along the flow.
    for dx, dy, r in ((955, 862, 10), (972, 912, 7), (928, 962, 8)):
        ellipse(rows, dx, dy, r, r, (120, 130, 250), 1.0)
        if 0 <= dx - 3 < W and 0 <= dy - 3 < H:
            row = rows[dy - 3]
            j = (dx - 3) * 3
            row[j] = min(255, row[j] + 110)
            row[j + 1] = min(255, row[j + 1] + 110)
            row[j + 2] = 255


# ----------------------------------------------------------------- crack ---
CRACK_LOCAL = [(127, -70), (148, -38), (134, -8), (162, 22),
               (148, 52), (178, 78), (196, 88), (220, 98)]
CRACK_HALF = [6.0, 8.0, 7.0, 9.0, 8.0, 10.0, 9.0, 11.0]


def strip_poly(pts, half):
    """A jagged strip polygon around a polyline, for the crack's gap."""
    left, right = [], []
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        if i == 0:
            dx, dy = pts[1][0] - x, pts[1][1] - y
        elif i == n - 1:
            dx, dy = x - pts[i - 1][0], y - pts[i - 1][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln, dx / ln
        h = half[i]
        left.append((x + nx * h, y + ny * h))
        right.append((x - nx * h, y - ny * h))
    return left + right[::-1]


def draw_crack(rows):
    pts = xfs(CRACK_LOCAL)
    poly(rows, strip_poly(pts, CRACK_HALF), (12, 7, 26), 1.0)
    for i in range(len(pts) - 1):
        seg(rows, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
            9.0, (196, 168, 255), 0.35, add=True)
    for i in range(len(pts) - 1):
        seg(rows, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
            3.0, WHITE, 0.95, add=True)
    for (x, y, r, a) in ((pts[0][0], pts[0][1], 46, 0.5),
                         (pts[3][0], pts[3][1], 55, 0.4),
                         (EXIT[0], EXIT[1], 66, 0.55)):
        disc(rows, x, y, r, (190, 172, 255), a)
    # Compact starburst where the spill breaks out.
    ex, ey = EXIT
    disc(rows, ex, ey, 12, WHITE, 1.0)
    for sp in ([(ex, ey - 34), (ex + 5, ey - 4), (ex, ey), (ex - 5, ey - 4)],
               [(ex, ey + 30), (ex + 5, ey + 4), (ex, ey), (ex - 5, ey + 4)],
               [(ex - 30, ey), (ex - 4, ey + 5), (ex, ey), (ex - 4, ey - 5)],
               [(ex + 30, ey), (ex + 4, ey + 5), (ex, ey), (ex + 4, ey - 5)]):
        poly(rows, sp, WHITE, 0.9, add=True)


# ---------------------------------------------------------------- render ---
def render():
    rows = build_background()
    draw_stars(rows)
    draw_padlock(rows)
    draw_shackle(rows)
    draw_ribbon(rows)
    draw_pool(rows)
    draw_spill_details(rows)
    draw_crack(rows)
    return rows


# ------------------------------------------------------------- PNG write ---
def _chunk(kind, data):
    body = kind + data
    return (struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def encode_png(rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter: none
        raw += row
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    out += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    out += _chunk(b"IEND", b"")
    return bytes(out)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "entry.png"), "wb") as fh:
        fh.write(encode_png(render()))


if __name__ == "__main__":
    main()
