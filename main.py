#!/usr/bin/env python3
"""Draw one exciting image: an impossible triangle fracturing with light.

A glowing Penrose triangle in molten gold hangs in deep indigo space. At its
top vertex the shape is splitting open: a white-hot burst, a beam of light
escaping upward, shockwave rings racing outward, cracks down the bars, and
crystalline shards flying along radial streaks. Pure standard library; the
output is fully deterministic (fixed arithmetic, fixed pseudo-random seeds).
"""

import math
import os
import struct
import zlib

# ---------------------------------------------------------------- canvas ---
WIDTH = 1024
HEIGHT = 1024

# Triangle centre and circumradius; the top vertex is the fracture point.
CX = 512.0
CY = 550.0
RADIUS = 308.0
BAR_W = 70.0          # bar thickness, perpendicular to each edge
STRIP_W = 18.0        # width of the darker side-face strip on each bar
ARM_FRAC = 0.58       # how far each chevron arm reaches along its edge

# Fracture point: the top vertex of the triangle.
FX = 512.0
FY = CY - RADIUS  # 257.0


# -------------------------------------------------------------- palette ---
def _lerp(a, b, t):
    return a + (b - a) * t


def _build_palette():
    """256-entry RGB palette, indexed by glow energy 0..255.

    Deep indigo at rest, through violet and magenta, to gold and white-hot.
    """
    stops = [
        (0, (4, 5, 13)),
        (48, (9, 12, 32)),
        (96, (22, 20, 62)),
        (140, (52, 28, 96)),
        (175, (104, 36, 130)),
        (200, (168, 48, 138)),
        (222, (226, 92, 96)),
        (240, (251, 168, 84)),
        (250, (253, 224, 148)),
        (255, (255, 255, 255)),
    ]
    pal = []
    for i in range(256):
        for k in range(len(stops) - 1):
            lo_e, lo_c = stops[k]
            hi_e, hi_c = stops[k + 1]
            if lo_e <= i <= hi_e:
                t = 0.0 if hi_e == lo_e else (i - lo_e) / (hi_e - lo_e)
                pal.append(bytes((
                    int(_lerp(lo_c[0], hi_c[0], t) + 0.5),
                    int(_lerp(lo_c[1], hi_c[1], t) + 0.5),
                    int(_lerp(lo_c[2], hi_c[2], t) + 0.5),
                )))
                break
    return pal


PALETTE = _build_palette()


def _build_glow_lut():
    """Map squared distance from the fracture point to a palette entry.

    Bucket = r^2 >> 10, covering the whole canvas. The glow falls off as a
    gaussian with a wide shoulder so the field stays alive far from the burst.
    """
    max_r2 = WIDTH * WIDTH + HEIGHT * HEIGHT
    n = (max_r2 >> 10) + 2
    lut = []
    for b in range(n):
        r2 = b << 10
        g = 150.0 * math.exp(-r2 / (2.0 * 250.0 * 250.0))
        g += 50.0 * math.exp(-r2 / (2.0 * 600.0 * 600.0))
        e = int(g + 6.0)
        if e > 255:
            e = 255
        lut.append(PALETTE[e])
    return lut


GLOW_LUT = _build_glow_lut()


# ----------------------------------------------------------- framebuffer ---
def new_framebuffer():
    """Background pass: radial glow field around the fracture point."""
    dx2 = [float((x - FX) * (x - FX)) for x in range(WIDTH)]
    lut = GLOW_LUT
    rows = []
    for y in range(HEIGHT):
        dy2 = float((y - FY) * (y - FY))
        rows.append(bytearray(b"".join(
            lut[int((d + dy2) // 1024)] for d in dx2
        )))
    return rows


# ------------------------------------------------------------ draw utils ---
def blend_span(row, x0f, x1f, rgb, alpha, additive):
    """Blend one horizontal span [x0f, x1f) with edge coverage."""
    if x1f <= 0.0 or x0f >= WIDTH:
        return
    x0 = int(math.floor(x0f))
    x1 = int(math.ceil(x1f))
    if x0 < 0:
        x0 = 0
    if x1 > WIDTH:
        x1 = WIDTH
    r, g, b = rgb
    if additive:
        for x in range(x0, x1):
            cov = min(x + 1.0, x1f) - max(x * 1.0, x0f)
            if cov <= 0.0:
                continue
            if cov > 1.0:
                cov = 1.0
            a = alpha * cov
            i = x * 3
            v = row[i] + int(r * a)
            row[i] = 255 if v > 255 else v
            v = row[i + 1] + int(g * a)
            row[i + 1] = 255 if v > 255 else v
            v = row[i + 2] + int(b * a)
            row[i + 2] = 255 if v > 255 else v
    else:
        for x in range(x0, x1):
            cov = min(x + 1.0, x1f) - max(x * 1.0, x0f)
            if cov <= 0.0:
                continue
            if cov > 1.0:
                cov = 1.0
            a = alpha * cov
            ia = 1.0 - a
            i = x * 3
            row[i] = int(row[i] * ia + r * a + 0.5)
            row[i + 1] = int(row[i + 1] * ia + g * a + 0.5)
            row[i + 2] = int(row[i + 2] * ia + b * a + 0.5)


def fill_poly(rows, pts, rgb, alpha=1.0, additive=False):
    """Scanline polygon fill with fractional edge coverage."""
    ys = [p[1] for p in pts]
    y0 = max(0, int(math.floor(min(ys))))
    y1 = min(HEIGHT - 1, int(math.ceil(max(ys))))
    n = len(pts)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x_a, y_a = pts[i]
            x_b, y_b = pts[(i + 1) % n]
            if (y_a <= yc < y_b) or (y_b <= yc < y_a):
                t = (yc - y_a) / (y_b - y_a)
                xs.append(x_a + t * (x_b - x_a))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            blend_span(rows[y], xs[k], xs[k + 1], rgb, alpha, additive)


def draw_line(rows, x0, y0, x1, y1, width, rgb, alpha=1.0, additive=False):
    """A thick line segment, drawn as a quad."""
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    nx = -dy / length * (width * 0.5)
    ny = dx / length * (width * 0.5)
    fill_poly(rows, [
        (x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
        (x1 - nx, y1 - ny), (x0 - nx, y0 - ny),
    ], rgb, alpha, additive)


def draw_ring(rows, cx, cy, radius, width, rgb, alpha, additive=True):
    """A soft-edged ring: three nested bands, brightest in the middle."""
    y0 = max(0, int(math.floor(cy - radius - width)))
    y1 = min(HEIGHT - 1, int(math.ceil(cy + radius + width)))
    r_out = radius + width * 0.5
    r_mid = radius
    r_in = radius - width * 0.5
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - cy
        dy2 = dy * dy
        if dy2 > r_out * r_out:
            continue
        xo = math.sqrt(r_out * r_out - dy2)
        xm = math.sqrt(max(0.0, r_mid * r_mid - dy2)) if dy2 < r_mid * r_mid else 0.0
        xi = math.sqrt(max(0.0, r_in * r_in - dy2)) if dy2 < r_in * r_in else 0.0
        for sgn in (1.0, -1.0):
            if sgn > 0:
                blend_span(rows[y], cx + xi, cx + xm, rgb, alpha * 0.55, additive)
                blend_span(rows[y], cx + xm, cx + xo, rgb, alpha * 0.55, additive)
            else:
                blend_span(rows[y], cx - xm, cx - xi, rgb, alpha * 0.55, additive)
                blend_span(rows[y], cx - xo, cx - xm, rgb, alpha * 0.55, additive)


def draw_disc(rows, cx, cy, radius, rgb, alpha):
    """Additive disc with a smooth gaussian-ish falloff."""
    y0 = max(0, int(math.floor(cy - radius)))
    y1 = min(HEIGHT - 1, int(math.ceil(cy + radius)))
    inv = 1.0 / (radius * radius)
    for y in range(y0, y1 + 1):
        dy = (y + 0.5) - cy
        half = math.sqrt(max(0.0, radius * radius - dy * dy))
        x0 = int(math.floor(cx - half))
        x1 = int(math.ceil(cx + half))
        if x0 < 0:
            x0 = 0
        if x1 > WIDTH:
            x1 = WIDTH
        row = rows[y]
        for x in range(x0, x1):
            dx = (x + 0.5) - cx
            t = (dx * dx + dy * dy) * inv
            if t >= 1.0:
                continue
            a = alpha * (1.0 - t) * (1.0 - t)
            i = x * 3
            v = row[i] + int(rgb[0] * a)
            row[i] = 255 if v > 255 else v
            v = row[i + 1] + int(rgb[1] * a)
            row[i + 1] = 255 if v > 255 else v
            v = row[i + 2] + int(rgb[2] * a)
            row[i + 2] = 255 if v > 255 else v


# ------------------------------------------------------- deterministic rng ---
class LCG:
    """Tiny fixed-seed generator: identical output on every run."""

    def __init__(self, seed):
        self.s = seed & 0x7FFFFFFF

    def next(self):
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s / 2147483648.0


# -------------------------------------------------------------- geometry ---
def triangle_vertices():
    verts = []
    for k in range(3):
        ang = math.radians(-90.0 + 120.0 * k)
        verts.append((CX + RADIUS * math.cos(ang), CY + RADIUS * math.sin(ang)))
    return verts  # [top, right, left]


def _unit(ax, ay):
    ln = math.hypot(ax, ay)
    return (ax / ln, ay / ln)


def chevron(vert, nxt, prv):
    """One corner piece of the impossible triangle.

    Returns (front_poly, inner_corner, arm_end_1, arm_end_2, arm_dir_1,
    arm_normal_1, arm_dir_2, arm_normal_2, edge_len) where each arm end is
    the (outer, inner) pair of points at the square-cut tip of that arm.
    """
    ux1, uy1 = _unit(nxt[0] - vert[0], nxt[1] - vert[1])  # toward nxt
    ux2, uy2 = _unit(prv[0] - vert[0], prv[1] - vert[1])  # toward prv
    edge_len = math.hypot(nxt[0] - vert[0], nxt[1] - vert[1])
    arm = ARM_FRAC * edge_len
    # Inward normals: pick the perpendicular pointing toward the centre.
    nx1, ny1 = -uy1, ux1
    if nx1 * (CX - vert[0]) + ny1 * (CY - vert[1]) < 0:
        nx1, ny1 = -nx1, -ny1
    nx2, ny2 = -uy2, ux2
    if nx2 * (CX - vert[0]) + ny2 * (CY - vert[1]) < 0:
        nx2, ny2 = -nx2, -ny2
    # Inner corner: intersection of the two inward-offset edge lines. A point
    # on the bisector at distance d from the vertex sits d*sin(30deg) from
    # each edge, so d = BAR_W / 0.5 puts it exactly BAR_W inside both.
    mx, my = _unit(nx1 + nx2, ny1 + ny2)
    inner = (vert[0] + mx * (BAR_W / 0.5),
             vert[1] + my * (BAR_W / 0.5))
    a1o = (vert[0] + ux1 * arm, vert[1] + uy1 * arm)
    a1i = (a1o[0] + nx1 * BAR_W, a1o[1] + ny1 * BAR_W)
    a2o = (vert[0] + ux2 * arm, vert[1] + uy2 * arm)
    a2i = (a2o[0] + nx2 * BAR_W, a2o[1] + ny2 * BAR_W)
    front = [vert, a1o, a1i, inner, a2i, a2o]
    return (front, inner, (a1o, a1i), (a2o, a2i),
            (ux1, uy1), (nx1, ny1), (ux2, uy2), (nx2, ny2), edge_len)


# ----------------------------------------------------------------- scene ---
GOLD_BRIGHT = (255, 214, 120)
GOLD_MID = (244, 164, 54)
GOLD_DEEP = (176, 96, 22)
GOLD_DARK = (110, 58, 16)
CYAN = (56, 224, 255)
WHITE = (255, 255, 255)


def draw_stars(rows):
    rng = LCG(20261116)
    for _ in range(340):
        x = rng.next() * WIDTH
        y = rng.next() * HEIGHT
        t = rng.next()
        if t < 0.62:
            bright = 70 + int(90 * rng.next())
            c = (bright, bright, min(255, bright + 25))
            if 0 <= int(x) < WIDTH and 0 <= int(y) < HEIGHT:
                row = rows[int(y)]
                i = int(x) * 3
                row[i] = min(255, row[i] + c[0] // 2)
                row[i + 1] = min(255, row[i + 1] + c[1] // 2)
                row[i + 2] = min(255, row[i + 2] + c[2] // 2)
        elif t < 0.9:
            bright = 150 + int(80 * rng.next())
            xi, yi = int(x), int(y)
            if 1 <= xi < WIDTH - 1 and 1 <= yi < HEIGHT - 1:
                for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    row = rows[yi + dy]
                    i = (xi + dx) * 3
                    row[i] = min(255, row[i] + bright // 2)
                    row[i + 1] = min(255, row[i + 1] + bright // 2)
                    row[i + 2] = min(255, row[i + 2] + bright // 2)
        else:
            # A few plus-shaped flares.
            xi, yi = int(x), int(y)
            if 3 <= xi < WIDTH - 3 and 3 <= yi < HEIGHT - 3:
                for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
                               (-2, 0), (2, 0), (0, -2), (0, 2)):
                    row = rows[yi + dy]
                    i = (xi + dx) * 3
                    add = 120 if dx == 0 and dy == 0 else 55
                    row[i] = min(255, row[i] + add)
                    row[i + 1] = min(255, row[i + 1] + add)
                    row[i + 2] = min(255, row[i + 2] + add)


def draw_beam(rows):
    """The escaping beam: a widening shaft of light above the fracture."""
    # Wide soft shaft, leaning slightly right.
    fill_poly(rows, [(FX - 26, FY - 6), (FX + 26, FY - 6),
                     (FX + 150, -20), (FX - 60, -20)],
              (255, 226, 160), 0.14, additive=True)
    # Bright core.
    fill_poly(rows, [(FX - 9, FY - 4), (FX + 9, FY - 4),
                     (FX + 52, -20), (FX + 6, -20)],
              (255, 250, 230), 0.55, additive=True)
    # Faint second shaft, leaning left.
    fill_poly(rows, [(FX - 14, FY - 2), (FX + 4, FY - 2),
                     (FX - 190, -20), (FX - 240, -20)],
              (150, 220, 255), 0.12, additive=True)


def draw_rings(rows):
    draw_ring(rows, FX, FY, 165, 7, CYAN, 0.75)
    draw_ring(rows, FX, FY, 250, 5, (120, 235, 255), 0.5)
    draw_ring(rows, FX, FY, 355, 5, (255, 214, 150), 0.38)
    draw_ring(rows, FX, FY, 480, 6, CYAN, 0.30)
    draw_ring(rows, FX, FY, 620, 7, (150, 140, 255), 0.22)
    draw_ring(rows, FX, FY, 770, 8, (120, 120, 220), 0.16)


def draw_streaks(rows):
    """Thin radial streaks carrying shards away from the fracture."""
    for ang, length, wdt, col in streak_defs():
        x0 = FX + math.cos(ang) * 70.0
        y0 = FY + math.sin(ang) * 70.0
        x1 = FX + math.cos(ang) * length
        y1 = FY + math.sin(ang) * length
        draw_line(rows, x0, y0, x1, y1, wdt, col, 0.5, additive=True)


def streak_defs():
    """Shared streak definitions so shards sit on the streaks."""
    rng = LCG(777)
    defs = []
    for k in range(9):
        ang = math.radians(-160.0 + k * 32.0 + rng.next() * 14.0)
        # Skip the upward beam sector; streaks fly sideways and down.
        if -110.0 < math.degrees(ang) < -70.0:
            continue
        length = 300.0 + rng.next() * 320.0
        wdt = 2.0 + rng.next() * 2.5
        col = GOLD_BRIGHT if k % 3 else CYAN
        defs.append((ang, length, wdt, col))
    return defs


def draw_shards(rows):
    """Elongated crystalline shards flung outward along the streaks."""
    rng = LCG(4242)
    for ang, length, _, _ in streak_defs():
        for _ in range(2):
            if rng.next() < 0.3:
                continue
            dist = length * (0.42 + rng.next() * 0.42)
            cx = FX + math.cos(ang) * dist
            cy = FY + math.sin(ang) * dist
            if not (20 < cx < WIDTH - 20 and 20 < cy < HEIGHT - 20):
                continue
            size = 9.0 + rng.next() * 15.0
            px, py = -math.sin(ang), math.cos(ang)  # perpendicular
            tip = (cx + math.cos(ang) * size, cy + math.sin(ang) * size)
            b1 = (cx - math.cos(ang) * size * 0.55 + px * size * 0.38,
                  cy - math.sin(ang) * size * 0.55 + py * size * 0.38)
            b2 = (cx - math.cos(ang) * size * 0.55 - px * size * 0.38,
                  cy - math.sin(ang) * size * 0.55 - py * size * 0.38)
            col = GOLD_BRIGHT if rng.next() < 0.6 else (200, 240, 255)
            fill_poly(rows, [tip, b1, b2], col, 0.92, additive=False)
            fill_poly(rows, [tip, b1, b2], WHITE, 0.3, additive=True)


def draw_triangle(rows):
    verts = triangle_vertices()
    chevrons = []
    for i in range(3):
        chevrons.append(chevron(verts[i], verts[(i + 1) % 3],
                                verts[(i - 1) % 3]))
    # Under-glow: a soft halo behind the whole triangle, a violet lift
    # inside the void so the hole reads as trapped light, and a wide glow
    # pool below so the lower third stays alive instead of empty.
    draw_disc(rows, CX, CY, 430, (120, 70, 20), 0.30)
    draw_disc(rows, CX, CY, 210, (96, 44, 128), 0.5)
    draw_disc(rows, CX, 940, 330, (64, 38, 128), 0.40)
    draw_disc(rows, CX, 880, 210, (110, 62, 20), 0.22)
    # Faces in cyclic order. The three bars get strongly separated golds --
    # pale, mid, deep bronze -- so each bar reads as its own piece even at
    # small size. Each chevron carries its own bevel strip, drawn with it,
    # so the side faces break at the overlaps instead of unifying the loop
    # into one flat frame.
    shades = [(255, 224, 150), (236, 152, 44), (178, 98, 20)]
    bevels = [(206, 138, 50), (168, 96, 26), (122, 62, 14)]
    inners = [c[1] for c in chevrons]
    for i, ch in enumerate(chevrons):
        (front, _, end1, end2, _, nrm1, _, nrm2, _) = ch
        vert = verts[i]
        fill_poly(rows, front, shades[i], 1.0)
        # Bevel strips along both arms, mitred at the vertex: the strip's
        # inner corner sits on the vertex bisector at the strip's depth.
        t = STRIP_W / BAR_W
        bev_v = (vert[0] + (inners[i][0] - vert[0]) * t,
                 vert[1] + (inners[i][1] - vert[1]) * t)
        a1o, _ = end1
        a2o, _ = end2
        b1 = (a1o[0] + nrm1[0] * STRIP_W, a1o[1] + nrm1[1] * STRIP_W)
        b2 = (a2o[0] + nrm2[0] * STRIP_W, a2o[1] + nrm2[1] * STRIP_W)
        fill_poly(rows, [vert, a1o, b1, bev_v], bevels[i], 1.0)
        fill_poly(rows, [vert, a2o, b2, bev_v], bevels[i], 1.0)
        draw_line(rows, bev_v[0], bev_v[1], b1[0], b1[1], 2.5,
                  (255, 226, 160), 0.7)
        draw_line(rows, bev_v[0], bev_v[1], b2[0], b2[1], 2.5,
                  (255, 226, 160), 0.7)
    # Cap: redraw the tip of chevron 0's second arm over chevron 2, closing
    # the impossible cycle (chevron 0 passes over chevron 2 here), with its
    # bevel strip and fold line redrawn too.
    v0 = verts[0]
    (_, _, _, _, _, _, (ux2, uy2), (nx2, ny2), edge_len) = chevrons[0]
    e0, e1 = 0.40 * edge_len, ARM_FRAC * edge_len
    cap_o0 = (v0[0] + ux2 * e0, v0[1] + uy2 * e0)
    cap_o1 = (v0[0] + ux2 * e1, v0[1] + uy2 * e1)
    cap_i0 = (cap_o0[0] + nx2 * BAR_W, cap_o0[1] + ny2 * BAR_W)
    cap_i1 = (cap_o1[0] + nx2 * BAR_W, cap_o1[1] + ny2 * BAR_W)
    fill_poly(rows, [cap_o0, cap_o1, cap_i1, cap_i0], shades[0], 1.0)
    cap_b0 = (cap_o0[0] + nx2 * STRIP_W, cap_o0[1] + ny2 * STRIP_W)
    cap_b1 = (cap_o1[0] + nx2 * STRIP_W, cap_o1[1] + ny2 * STRIP_W)
    fill_poly(rows, [cap_o0, cap_o1, cap_b1, cap_b0], bevels[0], 1.0)
    draw_line(rows, cap_b0[0], cap_b0[1], cap_b1[0], cap_b1[1], 2.5,
              (255, 226, 160), 0.7)
    # Hot rim along the inner void: light trapped inside the triangle.
    for i in range(3):
        a = inners[i]
        b = inners[(i + 1) % 3]
        draw_line(rows, a[0], a[1], b[0], b[1], 4.0, (255, 236, 180), 0.85,
                  additive=True)
    # Outer edge definition: thin dark keyline on the outer silhouette.
    for i in range(3):
        a = verts[i]
        b = verts[(i + 1) % 3]
        draw_line(rows, a[0], a[1], b[0], b[1], 2.0, GOLD_DARK, 0.8)
    # Over/under breaks: at each arm-2 end the over bar's cut edge gets a
    # cast-shadow band on the bar passing beneath it, a thick dark seam,
    # and a bright lip highlight, so the impossible cycle reads instantly.
    for ch in chevrons:
        (_, _, _, (s_o, s_i), _, _, (dx, dy), _, _) = ch
        sh_o = (s_o[0] + dx * 15.0, s_o[1] + dy * 15.0)
        sh_i = (s_i[0] + dx * 15.0, s_i[1] + dy * 15.0)
        fill_poly(rows, [s_o, s_i, sh_i, sh_o], (28, 14, 6), 0.5)
        draw_line(rows, s_o[0], s_o[1], s_i[0], s_i[1], 6.0,
                  (46, 22, 8), 1.0)
        hl_o = (s_o[0] - dx * 3.0, s_o[1] - dy * 3.0)
        hl_i = (s_i[0] - dx * 3.0, s_i[1] - dy * 3.0)
        draw_line(rows, hl_o[0], hl_o[1], hl_i[0], hl_i[1], 2.5,
                  (255, 238, 185), 0.9)


def _crack(rows, pts):
    """One fissure: a soft glow pass under a bright thin core pass."""
    for i in range(len(pts) - 1):
        draw_line(rows, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                  7.0, (255, 190, 90), 0.35, additive=True)
    for i in range(len(pts) - 1):
        draw_line(rows, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                  3.0, WHITE, 0.95, additive=True)


def draw_cracks(rows):
    """Bright fissures splitting from the fracture down each bar's middle.

    Each crack follows its bar's centreline (apex, then down the bar at 30
    degrees from vertical, offset half a bar width toward the void), so the
    fissures stay on the gold instead of wandering onto the background.
    """
    _crack(rows, [(FX - 4, FY + 6), (FX - 7, FY + 45), (FX + 6, FY + 75),
                  (FX - 24, FY + 117), (FX - 42, FY + 155),
                  (FX - 74, FY + 197), (FX - 97, FY + 240),
                  (FX - 120, FY + 280)])
    _crack(rows, [(FX + 4, FY + 6), (FX + 8, FY + 43), (FX - 2, FY + 75),
                  (FX + 28, FY + 115), (FX + 44, FY + 153),
                  (FX + 76, FY + 195), (FX + 98, FY + 237),
                  (FX + 122, FY + 277)])
    # Short crack into the void, plus one branch off the left crack.
    _crack(rows, [(FX, FY + 13), (FX + 10, FY + 75), (FX - 2, FY + 140)])
    _crack(rows, [(FX - 24, FY + 117), (FX - 54, FY + 133),
                  (FX - 76, FY + 159)])


def draw_burst(rows):
    """The white-hot starburst at the fracture point.

    Kept compact on purpose: a hot point splitting the apex, not a sun that
    swallows the triangle. The upward spike merges into the escaping beam.
    """
    draw_disc(rows, FX, FY, 58, (255, 240, 200), 0.85)
    draw_disc(rows, FX, FY, 24, WHITE, 0.95)
    # Four-point star: long vertical/horizontal spikes, short diagonals.
    spikes = [
        [(FX, FY - 96), (FX + 6, FY - 8), (FX, FY), (FX - 6, FY - 8)],
        [(FX, FY + 72), (FX + 6, FY + 8), (FX, FY), (FX - 6, FY + 8)],
        [(FX - 72, FY), (FX - 8, FY + 6), (FX, FY), (FX - 8, FY - 6)],
        [(FX + 72, FY), (FX + 8, FY + 6), (FX, FY), (FX + 8, FY - 6)],
        [(FX - 38, FY - 38), (FX - 4, FY - 4), (FX, FY), (FX - 4, FY - 4)],
        [(FX + 38, FY - 38), (FX + 4, FY - 4), (FX, FY), (FX + 4, FY - 4)],
        [(FX - 38, FY + 38), (FX - 4, FY + 4), (FX, FY), (FX - 4, FY + 4)],
        [(FX + 38, FY + 38), (FX + 4, FY + 4), (FX, FY), (FX + 4, FY + 4)],
    ]
    for sp in spikes:
        fill_poly(rows, sp, WHITE, 0.9, additive=True)
    draw_disc(rows, FX, FY, 10, WHITE, 1.0)


def draw_split(rows):
    """The fracture splitting the apex open.

    A jagged gap is cut through the top corner: a dark shadow wedge first,
    then a narrower light-filled wedge inside it, so the escaping beam
    reads as light shining THROUGH the split rather than a burst sitting
    on top of the shape. Small gold shards, each dark-outlined, sit
    displaced just outside the gap edges, and a white-hot core runs down
    the middle of the break.
    """
    dark = [(FX - 4, FY - 12), (FX - 14, FY + 16), (FX - 7, FY + 40),
            (FX - 16, FY + 62), (FX - 5, FY + 86), (FX, FY + 96),
            (FX + 5, FY + 86), (FX + 15, FY + 60), (FX + 6, FY + 38),
            (FX + 13, FY + 14), (FX + 4, FY - 12)]
    fill_poly(rows, dark, (14, 8, 30), 1.0)
    light = [(FX - 2, FY - 12), (FX - 9, FY + 16), (FX - 4, FY + 40),
             (FX - 10, FY + 62), (FX - 3, FY + 86), (FX, FY + 94),
             (FX + 3, FY + 86), (FX + 9, FY + 60), (FX + 4, FY + 38),
             (FX + 8, FY + 14), (FX + 2, FY - 12)]
    fill_poly(rows, light, (255, 228, 165), 0.9, additive=True)
    core = [(FX, FY - 8), (FX - 3, FY + 18), (FX + 2, FY + 42),
            (FX - 2, FY + 66), (FX, FY + 90)]
    for i in range(len(core) - 1):
        draw_line(rows, core[i][0], core[i][1], core[i + 1][0],
                  core[i + 1][1], 3.0, WHITE, 0.95, additive=True)
    # Displaced shards: gold fragments pushed out of the break.
    shards = [
        [(FX - 18, FY + 6), (FX - 38, FY + 20), (FX - 20, FY + 30)],
        [(FX + 17, FY + 12), (FX + 36, FY + 28), (FX + 19, FY + 35)],
        [(FX - 14, FY + 50), (FX - 30, FY + 62), (FX - 15, FY + 70)],
        [(FX + 13, FY + 56), (FX + 28, FY + 68), (FX + 14, FY + 75)],
    ]
    for j, sh in enumerate(shards):
        col = GOLD_BRIGHT if j % 2 == 0 else GOLD_MID
        fill_poly(rows, sh, col, 1.0)
        for k in range(3):
            a = sh[k]
            b = sh[(k + 1) % 3]
            draw_line(rows, a[0], a[1], b[0], b[1], 2.0, GOLD_DARK, 0.9)


def render():
    rows = new_framebuffer()
    draw_stars(rows)
    draw_rings(rows)
    draw_streaks(rows)
    draw_beam(rows)
    draw_triangle(rows)
    draw_shards(rows)
    draw_cracks(rows)
    draw_split(rows)
    draw_burst(rows)
    return rows


# -------------------------------------------------------------- PNG write ---
def _chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data +
            struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def encode_png(rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter: none
        raw.extend(row)
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    return bytes(png)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    png = encode_png(render())
    with open(os.path.join(out_dir, "entry.png"), "wb") as fh:
        fh.write(png)


if __name__ == "__main__":
    main()
