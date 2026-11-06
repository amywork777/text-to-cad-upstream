#!/usr/bin/env python3
"""Studio's CAD icons, line glyphs drawn on one isometric grid.

Every icon is one weight of line in the text's own color (currentColor, so light and dark and a
pressed button need nothing of their own): no fills, no tones, no gradients. Solids are built from
boxes and cylinders in model space, projected the same way (2:1 isometric, 1 unit = 1 px at 32 px),
with only the edges one can see; a line stays WEIGHT px at every size. Each command has a silhouette
of its own, so nothing leans on color to be told apart. What a tool takes away, or what was there
before, is dashed. A dot of the same ink marks a point: where a sketch tool's click goes, or what a
pick takes; a face a pick takes is hatched. Red, amber and green say how something went, so no icon
wears them: the check is a status mark, not an icon.

With no arguments it prints the hidden <svg> of <symbol>s the mockup uses. `--jsx [OUT]` writes the
viewer's module instead (src/lib/nxIcons.generated.jsx unless OUT is given): the sprite as a
component, the icons' names, and NxIcon, which draws one by name. `--sheet OUT` writes a page of
every icon, named, at 16, 24 and 32 px on light and on dark. Run it again whenever an icon changes.
Every id is "nx-" and the icon's name, so nothing collides with the page the sprite is mounted in.
"""

import argparse
import html
import math
import os
import re
import sys
from xml.etree import ElementTree

WEIGHT = 1.25  # every line's width, in px at every size
DASH = "1 3.2"  # a line that is not there: a ghost, an axis, a reference. Round caps take a weight of each gap.
PREFIX = "nx-"  # on every id this writes
MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "lib", "nxIcons.generated.jsx")

CHECK = (
    f'<symbol id="{PREFIX}check" viewBox="0 0 12 12"><path d="m2.3 6.3 2.4 2.4 5-5.4" fill="none" '
    'stroke="#2e8540" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></symbol>'
)


def num(v):
    # Snapped to 9 places first, so a coordinate the trig puts a hair either side of a half (2.125)
    # rounds the same on every platform's libm, and the module is the same wherever it is written.
    v = round(round(v + 0.0, 9), 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0")


def polar(cx, cy, r, degrees):
    """The point `degrees` anticlockwise from +x on screen (whose y grows down) round (cx, cy)."""
    a = math.radians(degrees)
    return (cx + r * math.cos(a), cy - r * math.sin(a))


def ink(dash=None):
    """The icons' one line: WEIGHT px at every size, in the text's color."""
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'fill="none" stroke="currentColor" stroke-width="{num(WEIGHT)}" stroke-linecap="round" '
        f'stroke-linejoin="round" vector-effect="non-scaling-stroke"{extra}'
    )


class Icon:
    def __init__(self, name):
        self.name, self.id, self.parts, self.pts = name, PREFIX + name, [], []

    @staticmethod
    def P(x, y, z):
        return (x - y, (x + y) / 2 - z)

    def proj(self, pts3):
        return [self.P(*p) for p in pts3]

    @staticmethod
    def d(pts, closed=True):
        return "M" + " L".join(f"{num(x)} {num(y)}" for x, y in pts) + (" Z" if closed else "")

    def path(self, d, extent, dash=None):
        """A line along the path `d`; `extent`, the points its box must hold."""
        self.pts += list(extent)
        self.parts.append(f'<path d="{d}" {ink(dash)}/>')

    def line(self, pts, closed=False, dash=None):
        self.path(self.d(pts, closed), pts, dash)

    def wire(self, pts3, closed=False, dash=None):
        """A line through points in model space."""
        self.line(self.proj(pts3), closed, dash)

    def ellipse(self, cx, cy, rx, ry, dash=None):
        self.pts += [(cx - rx, cy - ry), (cx + rx, cy + ry)]
        self.parts.append(f'<ellipse cx="{num(cx)}" cy="{num(cy)}" rx="{num(rx)}" ry="{num(ry)}" {ink(dash)}/>')

    def circle(self, cx, cy, r, dash=None):
        self.ellipse(cx, cy, r, r, dash)

    def arc(self, cx, cy, r, a0, a1, dash=None):
        """An arc turning anticlockwise on screen from a0 to a1 degrees; returns its ends."""
        start, end = polar(cx, cy, r, a0), polar(cx, cy, r, a1)
        large = 1 if (a1 - a0) % 360 > 180 else 0
        extent = [polar(cx, cy, r, a0 + (a1 - a0) * i / 8) for i in range(9)]
        self.path(f"M{num(start[0])} {num(start[1])} A{num(r)} {num(r)} 0 {large} 0 {num(end[0])} {num(end[1])}", extent, dash)
        return start, end

    def node(self, x, y, s=1.7):
        """A point: where a click goes, or what a pick takes. A dot of the line's own ink."""
        box = [(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)]
        self.pts += box
        self.parts.append(f'<path d="{self.d(box)}" fill="currentColor"/>')

    def head(self, tip, behind, length=4.2, half=3):
        """An open arrowhead at tip, pointing away from behind."""
        dx, dy = tip[0] - behind[0], tip[1] - behind[1]
        n = math.hypot(dx, dy)
        ux, uy = dx / n, dy / n
        bx, by = tip[0] - ux * length, tip[1] - uy * length
        self.line([(bx - uy * half, by + ux * half), tip, (bx + uy * half, by - ux * half)])

    def arrow(self, start, tip, length=4.2, half=3):
        self.line([start, tip])
        self.head(tip, start, length, half)

    def cross(self, x, y, k=2.8):
        """Delete's mark, and a pick cut away."""
        self.line([(x - k, y - k), (x + k, y + k)])
        self.line([(x + k, y - k), (x - k, y + k)])

    def hatch(self, a0, a1, b0, b1, n=2):
        """`n` lines across a face, from its edge a0 to a1 to its edge b0 to b1: the face is what is picked."""
        for i in range(1, n + 1):
            t = i / (n + 1)
            self.wire([tuple(p + (q - p) * t for p, q in zip(a0, a1)), tuple(p + (q - p) * t for p, q in zip(b0, b1))])

    def block(self, x0, y0, z0, x1, y1, z1, dash=None):
        """A box: its outline and the three edges meeting at the corner nearest the eye."""
        P = self.P
        self.line([P(x0, y0, z1), P(x1, y0, z1), P(x1, y0, z0), P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1)], True, dash)
        if dash:
            return  # a ghost is its outline alone
        near = P(x1, y1, z1)
        self.line([P(x1, y0, z1), near, P(x0, y1, z1)])
        self.line([near, P(x1, y1, z0)])

    def plate(self, x0, y0, x1, y1, z=0, dash=None):
        """A flat face, seen from above: a plane, a sketch's page."""
        self.wire([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], True, dash)

    def cylinder(self, x, y, z0, z1, r):
        """An upright cylinder; r is its radius on screen."""
        cx, top = self.P(x, y, z1)
        _, bottom = self.P(x, y, z0)
        ry = r / 2
        L, R, T, B, rr = num(cx - r), num(cx + r), num(top), num(bottom), f"{num(r)} {num(ry)}"
        self.ellipse(cx, top, r, ry)
        self.path(f"M{L} {T} L{L} {B} A{rr} 0 0 0 {R} {B} L{R} {T}", [(cx - r, top), (cx + r, bottom + ry)])

    def hole(self, x, y, z, r, depth):
        """A round hole down from a face: its rim, and its far wall's foot seen through it."""
        cx, cy = self.P(x, y, z)
        ry = r / 2
        self.ellipse(cx, cy, r, ry)
        # the rim dropped `depth`, as far as the rim itself shows it
        inside = [(r * math.cos(math.radians(a)), ry * math.sin(math.radians(a)) + depth) for a in range(180, 361, 6)]
        seen = [(cx + px, cy + py) for px, py in inside if (px / r) ** 2 + (py / ry) ** 2 <= 1]
        if len(seen) > 1:
            self.line(seen)

    def pen(self, tip, length=16, width=5, chisel=False):
        """What draws at tip, leaning up to the right: a pen's outline, its cone, a chisel's flat nib."""
        ux, uy = math.sqrt(0.5), -math.sqrt(0.5)  # from the tip toward the end
        nx, ny = -uy, ux  # across

        def at(s, k):
            return (tip[0] + ux * s + nx * k * width / 2, tip[1] + uy * s + ny * k * width / 2)

        cone = 5
        nose = [at(0, -0.5), at(1.6, 0.5)] if chisel else [tip]
        self.line(nose + [at(cone, 1), at(length, 1), at(length, -1), at(cone, -1)], True)
        self.line([at(cone, -1), at(cone, 1)])

    def rubber(self, tip, length=12, width=8):
        """The eraser, rubbing at tip: a block with its sleeve."""
        ux, uy = math.sqrt(0.5), -math.sqrt(0.5)
        nx, ny = -uy, ux

        def at(s, k):
            return (tip[0] + ux * s + nx * k * width / 2, tip[1] + uy * s + ny * k * width / 2)

        self.line([at(0, -1), at(length, -1), at(length, 1), at(0, 1)], True)
        self.line([at(4.5, -1), at(4.5, 1)])

    def pointer(self, tip):
        """The pointer, its tip at `tip`: what Select picks with."""
        x, y = tip
        self.line([(x, y), (x, y + 10.6), (x + 2.7, y + 8.1), (x + 4.5, y + 12.2), (x + 6.4, y + 11.4), (x + 4.6, y + 7.4), (x + 8.2, y + 7.4)], True)

    def symbol(self, size=32):
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        print(f"{self.name}: {w:.1f} x {h:.1f}", file=sys.stderr)
        dx, dy = round(size - min(xs) - max(xs)) / 2, round(size - min(ys) - max(ys)) / 2
        return (
            f'<symbol id="{self.id}" viewBox="0 0 {size} {size}">'
            f'<g transform="translate({num(dx)} {num(dy)})">{"".join(self.parts)}</g></symbol>'
        )


def sketch():
    """A page with a pen on it; the page's edge breaks where the pen crosses."""
    ic = Icon("sketch")
    ic.line([(7, 3.5), (13, 6.5), (0, 13), (-13, 6.5), (0, 0)])
    ic.pen((-2, 7))
    return ic


def extrude():
    ic = Icon("extrude")
    ic.block(0, 0, 0, 11, 11, 7)
    ic.arrow(ic.P(5.5, 5.5, 7), (0, -14))
    return ic


def revolve():
    """A profile beside its axis, and a turn round the axis."""
    ic = Icon("revolve")
    axis, cy, rx, ry = -7, -9.5, 7.5, 3.4
    ic.line([(axis, -14), (axis, 13)], dash=DASH)
    ic.line([(-2, -1), (3, -1), (3, 6), (12, 6), (12, 12), (-2, 12)], True)
    ic.path(f"M{num(axis - rx)} {num(cy)} A{num(rx)} {num(ry)} 0 0 0 {num(axis + rx)} {num(cy)}",
            [(axis - rx, cy), (axis + rx, cy + ry)])
    ic.head((axis + rx, cy - 0.4), (axis + rx - 0.6, cy + 2.6), length=3.6, half=2.8)
    return ic


def hole():
    ic = Icon("hole")
    ic.block(0, 0, 0, 13, 13, 8)
    ic.hole(6.5, 6.5, 8, 6, 3.2)
    return ic


def rounded(kind):
    """A block with its top front-left edge blended or chamfered, at a size the end of it shows."""
    ic = Icon(kind)
    s, h, r = 13, 11, 8
    P = ic.P
    if kind == "blend":
        steps = [i * math.pi / 16 for i in range(9)]

        def prof(x):
            return [(x, s - r + r * math.sin(t), h - r + r * math.cos(t)) for t in steps]
    else:

        def prof(x):
            return [(x, s - r, h), (x, s, h - r)]

    ic.line([P(0, 0, h), P(s, 0, h), P(s, 0, 0), P(s, s, 0), P(0, s, 0)] + ic.proj(prof(0)[::-1]), True)
    ic.wire([(s, 0, h)] + prof(s) + [(s, s, 0)])
    ic.wire([prof(0)[0], prof(s)[0]])
    ic.wire([prof(0)[-1], prof(s)[-1]])
    return ic


def shell():
    """An open box: the wall's thickness round its rim, and inside it the corner going down to the floor."""
    ic = Icon("shell")
    s, h, t, down = 14, 8, 3.2, 3.6
    ic.block(0, 0, 0, s, s, h)
    ic.plate(t, t, s - t, s - t, h)
    floor = h - down
    ic.wire([(t, t, h), (t, t, floor)])
    ic.wire([(s - t - down, t, floor), (t, t, floor), (t, s - t - down, floor)])
    return ic


def frustum(ic, b, a, h):
    """A block tapered in by `a` on every side at its top."""
    P = ic.P
    ic.line([P(a, a, h), P(b - a, a, h), P(b, 0, 0), P(b, b, 0), P(0, b, 0), P(a, b - a, h)], True)
    ic.wire([(b - a, a, h), (b - a, b - a, h), (a, b - a, h)])
    ic.wire([(b - a, b - a, h), (b, b, 0)])


def draft():
    ic = Icon("draft")
    b, a, h = 13, 3, 9
    frustum(ic, b, a, h)
    # the pull direction, and the draft angle from it
    foot = ic.P(b, 0, 0)
    ic.line([foot, (foot[0], foot[1] - 15)], dash=DASH)
    r = 9.5
    up = (foot[0], foot[1] - r)
    tx, ty = ic.P(b - a, a, h)
    n = math.hypot(tx - foot[0], ty - foot[1])
    along = (foot[0] + (tx - foot[0]) / n * r, foot[1] + (ty - foot[1]) / n * r)
    ic.path(f"M{num(up[0])} {num(up[1])} A{num(r)} {num(r)} 0 0 0 {num(along[0])} {num(along[1])}", [up, along])
    return ic


def bracket(ic, s, t, H, creases=None):
    """An L: a base plate and a wall along its back. `creases`, the spans of the corner between them one sees."""
    P = ic.P
    ic.line([P(0, 0, H), P(t, 0, H), P(t, 0, t), P(s, 0, t), P(s, 0, 0), P(s, s, 0), P(0, s, 0), P(0, s, H)], True)
    ic.wire([(t, 0, H), (t, s, H), (0, s, H)])
    ic.wire([(t, s, H), (t, s, t), (s, s, t), (s, s, 0)])
    ic.wire([(s, 0, t), (s, s, t)])
    for y0, y1 in creases or ((0, s),):
        ic.wire([(t, y0, t), (t, y1, t)])


def rib():
    ic = Icon("rib")
    s, t, H = 13, 3, 12
    y0, y1, top, run = 5, 8, 10.5, 10.5
    # the rib hides the corner where a line of sight from it passes under the rib's slope
    bracket(ic, s, t, H, ((0, y0 - (top - t) / 2), (y1, s)))
    ic.wire([(t, y1, t), (run, y1, t), (t, y1, top), (t, y0, top), (run, y0, t), (run, y1, t)])
    return ic


def pattern():
    """A plate with the same hole four times over."""
    ic = Icon("pattern")
    s, t = 14, 2.5
    ic.block(0, 0, 0, s, s, t)
    for x, y in ((3.8, 3.8), (3.8, 10.2), (10.2, 3.8), (10.2, 10.2)):
        cx, cy = ic.P(x, y, t)
        ic.ellipse(cx, cy, 2.4, 1.2)
    return ic


def mirror():
    """A plane, the body on one side of it, its copy dashed on the other."""
    ic = Icon("mirror")
    ic.line([(-2.5, -12.5), (2.5, -10), (2.5, 12.5), (-2.5, 10)], True)
    ic.line([(-6.5, -6), (-6.5, 8), (-13.5, 8), (-13.5, 1)], True)
    ic.line([(6.5, -6), (6.5, 8), (13.5, 8), (13.5, 1)], True, DASH)
    return ic


def datum_plane():
    ic = Icon("plane")
    ic.plate(0, 0, 13, 13)
    ic.arrow(ic.P(6.5, 6.5, 0), (0, -9))
    return ic


def csys():
    ic = Icon("csys")
    o = ic.P(0, 0, 0)
    for end in ((14, 0, 0), (0, 14, 0), (0, 0, 13)):
        ic.arrow(o, ic.P(*end))
    return ic


def sweep():
    """A profile, and the path it follows to where it ends, dashed."""
    ic = Icon("sweep")
    ic.ellipse(-11.5, 7.5, 2.4, 5)
    ic.path("M-9.1 7.5 C-2 7.5 2 -7.5 9.1 -7.5", [(-9.1, 7.5), (9.1, -7.5)])
    ic.ellipse(11.5, -7.5, 2.4, 5, DASH)
    return ic


def loft():
    """Two different profiles, and the rails between them."""
    ic = Icon("loft")
    ic.ellipse(-10, 6, 3, 6.5)
    ic.path("M-10 -.5 C-3 -1.5 3 -11 8 -12", [(-10, -0.5), (8, -12)])
    ic.path("M-10 12.5 C-3 12 3 3 8 2", [(-10, 12.5), (8, 2)])
    ic.line([(8, -12), (12.5, -12), (12.5, 2), (8, 2)], True)
    return ic


def split():
    """A block, and the plane going through it: dashed where it is inside."""
    ic = Icon("split")
    s, h, cut = 13, 8, 6.5
    ic.block(0, 0, 0, s, s, h)
    ic.wire([(cut, 0, h), (cut, s, h), (cut, s, 0)], dash=DASH)
    ic.wire([(cut, -4, h), (cut, 0, h)])
    ic.wire([(cut, s, 0), (cut, s, -3.5)])
    return ic


def delete():
    ic = Icon("delete")
    ic.block(0, 0, 0, 10, 10, 7)
    ic.cross(10.5, 11)
    return ic


def body():
    """A body with no history, as an imported STEP is: a block and nothing on it."""
    ic = Icon("body")
    ic.block(0, 0, 0, 13, 13, 9)
    return ic


def offset_face():
    """NX's Offset Region: a body, the layer its top face gained, and the way it moves."""
    ic = Icon("offset-face")
    s, h = 12, 8
    ic.block(0, 0, 0, s, s, h)
    ic.wire([(0, s, h - 3.2), (s, s, h - 3.2), (s, 0, h - 3.2)])
    ic.arrow(ic.P(s / 2, s / 2, h), (0, -15))
    return ic


def delete_face():
    """Delete Face: a body with its right face gone to dashes, and Delete's mark."""
    ic = Icon("delete-face")
    s, h = 10, 7
    ic.plate(0, 0, s, s, h)
    ic.wire([(0, s, h), (0, s, 0), (s, s, 0), (s, s, h)])
    ic.wire([(s, 0, h), (s, 0, 0), (s, s, 0)], dash=DASH)
    ic.cross(10.5, 11)
    return ic


BUBBLE = (
    "M-7.5 -10 H7.5 A4.5 4.5 0 0 1 12 -5.5 V1 A4.5 4.5 0 0 1 7.5 5.5 H-1.5 L-6.5 10.5 V5.5 H-7.5 "
    "A4.5 4.5 0 0 1 -12 1 V-5.5 A4.5 4.5 0 0 1 -7.5 -10 Z"
)


def ask():
    ic = Icon("ask")
    ic.path(BUBBLE, [(-12, -10), (12, 10.5)])
    ic.path("M0 -7 C.6 -4.2 1.6 -3.3 4.6 -2.7 C1.6 -2.1 .6 -1.2 0 1.6 C-.6 -1.2 -1.6 -2.1 -4.6 -2.7 C-1.6 -3.3 -.6 -4.2 0 -7 Z", [])
    return ic


# The sketch tools, one each, flat: what each draws, or what it does to what is drawn, with a dot at
# each click it takes. What a tool takes away, or what was there before, is dashed.


def sketch_tool(name):
    """A sketch tool's icon: every one of them is "sketch-" and its name."""
    return Icon(f"sketch-{name}")


def sketch_line():
    ic = sketch_tool("line")
    ic.line([(-9.5, 8.5), (9.5, -8.5)])
    ic.node(-9.5, 8.5)
    ic.node(9.5, -8.5)
    return ic


RECTANGLE = [(-10.5, -7.5), (10.5, -7.5), (10.5, 7.5), (-10.5, 7.5)]


def sketch_rectangle():
    ic = sketch_tool("rectangle")
    ic.line(RECTANGLE, True)
    ic.node(-10.5, 7.5)
    ic.node(10.5, -7.5)
    return ic


def sketch_center_rectangle():
    ic = sketch_tool("center-rectangle")
    ic.line(RECTANGLE, True)
    ic.line([(0, 0), (10.5, -7.5)], dash=DASH)
    ic.node(0, 0)
    ic.node(10.5, -7.5)
    return ic


def sketch_three_point_rectangle():
    ic = sketch_tool("three-point-rectangle")
    a, b, c, d = (-9, 0.5), (3, -8.5), (9, -0.5), (-3, 8.5)
    ic.line([a, b, c, d], True)
    for x, y in (a, b, c):
        ic.node(x, y)
    return ic


def sketch_circle():
    ic = sketch_tool("circle")
    ic.circle(0, 0, 9.5)
    edge_at = polar(0, 0, 9.5, 45)
    ic.line([(0, 0), edge_at], dash=DASH)
    ic.node(0, 0)
    ic.node(*edge_at)
    return ic


def sketch_three_point_circle():
    ic = sketch_tool("three-point-circle")
    ic.circle(0, 0, 9.5)
    for degrees in (150, 30, 270):
        ic.node(*polar(0, 0, 9.5, degrees))
    return ic


def sketch_arc():
    ic = sketch_tool("arc")
    centre = (0, 6)
    start, end = ic.arc(*centre, 11.5, 25, 155)
    for at in (start, end):
        ic.line([centre, at], dash=DASH)
    for at in (centre, start, end):
        ic.node(*at)
    return ic


def sketch_three_point_arc():
    ic = sketch_tool("three-point-arc")
    start, end, top = (-10, 5), (10, 5), (0, -6)
    # its centre (0, c), as far from an end as from the top: 10**2 + (5 - c)**2 = (c + 6)**2
    c = (10 ** 2 + 5 ** 2 - 6 ** 2) / (2 * 5 + 2 * 6)
    spread = math.degrees(math.atan2(c - end[1], end[0]))
    ic.arc(0, c, c - top[1], spread, 180 - spread)
    for at in (start, top, end):
        ic.node(*at)
    return ic


def sketch_tangent_arc():
    ic = sketch_tool("tangent-arc")
    ic.line([(-11, 7), (-2, 7)])
    _, end = ic.arc(-2, -3, 10, 270, 360)
    ic.node(-2, 7)
    ic.node(*end)
    return ic


def slot_path(half=6, r=5.5):
    return (f"M{num(-half)} {num(-r)} H{num(half)} A{num(r)} {num(r)} 0 0 1 {num(half)} {num(r)} H{num(-half)} "
            f"A{num(r)} {num(r)} 0 0 1 {num(-half)} {num(-r)} Z"), [(-half - r, -r), (half + r, r)]


def sketch_slot():
    ic = sketch_tool("slot")
    ic.path(*slot_path())
    ic.node(-6, 0)
    ic.node(6, 0)
    return ic


def sketch_center_slot():
    ic = sketch_tool("center-slot")
    ic.path(*slot_path())
    ic.line([(-6, 0), (6, 0)], dash=DASH)
    ic.node(0, 0)
    ic.node(6, 0)
    return ic


def sketch_polygon():
    ic = sketch_tool("polygon")
    ic.line([polar(0, 0, 10.5, 60 * i) for i in range(6)], True)
    ic.line([(0, 0), (10.5, 0)], dash=DASH)
    ic.node(0, 0)
    ic.node(10.5, 0)
    return ic


def sketch_spline():
    ic = sketch_tool("spline")
    ic.path("M-10.5 6 C-8 -5 -3 -6 0 0 S8 6 10.5 -6", [(-10.5, -4), (10.5, 4), (-10.5, 6), (10.5, -6)])
    for x, y in ((-10.5, 6), (0, 0), (10.5, -6)):
        ic.node(x, y)
    return ic


def sketch_reference_line():
    ic = sketch_tool("reference-line")
    ic.line([(-9.5, 8.5), (9.5, -8.5)], dash=DASH)
    ic.node(-9.5, 8.5)
    ic.node(9.5, -8.5)
    return ic


def sketch_point():
    ic = sketch_tool("point")
    for degrees in (0, 90, 180, 270):
        ic.line([polar(0, 0, 5, degrees), polar(0, 0, 10, degrees)])
    ic.node(0, 0, 2)
    return ic


def dimension(ic, y, x0, x1, foot):
    """A dimension between x0 and x1 at height y, its extension lines down to `foot`."""
    for x in (x0, x1):
        ic.line([(x, foot), (x, y - 2.2)])
    ic.line([(x0, y), (x1, y)])
    ic.head((x0, y), (x1, y), length=3.4, half=2.4)
    ic.head((x1, y), (x0, y), length=3.4, half=2.4)


def sketch_dimension():
    ic = sketch_tool("dimension")
    ic.line([(-10.5, 9), (10.5, 9)])
    dimension(ic, 2, -10.5, 10.5, 7)
    ic.line([(-4.5, -9), (4.5, -9), (4.5, -3), (-4.5, -3)], True)
    for at in ((-10.5, 9), (10.5, 9)):
        ic.node(*at)
    return ic


def corner(kind):
    """A corner made round (Fillet) or cut (Chamfer), clicked at the sharp corner it was, dashed."""
    ic = sketch_tool(kind)
    ic.path("M-9 0 V-9 H0", [(-9, -9), (0, 0)], DASH)
    turn = "A9 9 0 0 1 0 -9" if kind == "fillet" else "L0 -9"
    ic.path(f"M-9 10.5 V0 {turn} H10.5", [(-9, -9), (10.5, 10.5)])
    ic.node(-9, -9)
    return ic


def sketch_trim():
    ic = sketch_tool("trim")
    ic.line([(3, -10), (3, 10)])
    ic.line([(-10.5, 1), (3, 1)])
    ic.line([(3, 1), (10.5, 1)], dash=DASH)
    ic.cross(7.5, 1, 2.4)
    return ic


def sketch_extend():
    ic = sketch_tool("extend")
    ic.line([(8, -10), (8, 10)])
    ic.line([(-10.5, 1), (-2, 1)])
    ic.line([(-2, 1), (4, 1)], dash=DASH)
    ic.head((7, 1), (0, 1), length=3.6, half=2.6)
    ic.node(-2, 1)
    return ic


def sketch_offset():
    ic = sketch_tool("offset")
    # a chain, and the same chain 6 in from it
    ic.path("M-10 10.5 V-1 A9 9 0 0 1 -1 -10 H10.5", [(-10, -10), (10.5, 10.5)], DASH)
    ic.path("M-4 10.5 V-1 A3 3 0 0 1 -1 -4 H10.5", [(-4, -4), (10.5, 10.5)])
    return ic


def sketch_mirror():
    ic = sketch_tool("mirror")
    ic.line([(0, -11), (0, 11)], dash=DASH)
    ic.line([(-2.5, -8), (-2.5, 8), (-10.5, 8)], True)
    ic.line([(2.5, -8), (2.5, 8), (10.5, 8)], True, DASH)
    return ic


def sketch_move():
    ic = sketch_tool("move")
    ic.circle(-6, 5, 5, DASH)
    ic.circle(6, -5, 5)
    ic.node(6, -5)
    return ic


def sketch_copy():
    ic = sketch_tool("copy")
    ic.circle(-6, 5, 5)
    ic.circle(6, -5, 5)
    ic.node(-6, 5)
    ic.node(6, -5)
    return ic


def sketch_rotate():
    ic = sketch_tool("rotate")
    pivot, turn = (-8, 9), math.radians(66)

    def turned(x, y):
        return (pivot[0] + x * math.cos(turn) + y * math.sin(turn), pivot[1] - x * math.sin(turn) + y * math.cos(turn))

    bar = [(0, 0), (16, 0), (16, -5), (0, -5)]
    ic.line([(pivot[0] + x, pivot[1] + y) for x, y in bar], True, DASH)
    ic.line([turned(x, y) for x, y in bar], True)
    ic.arc(*pivot, 19, 24, 62)
    ic.head(polar(*pivot, 19, 62), polar(*pivot, 19, 52), length=3.4, half=2.4)
    ic.node(*pivot)
    return ic


def sketch_scale():
    ic = sketch_tool("scale")
    ic.line([(-10, 9), (-10, -10), (9, -10), (9, 9)], True)
    ic.line([(-10, 9), (-10, 1), (-2, 1), (-2, 9)], True, DASH)
    ic.arrow((-1, 0), (5, -6), length=3.4, half=2.4)
    ic.node(-10, 9)
    return ic


def sketch_linear_pattern():
    ic = sketch_tool("linear-pattern")
    ic.circle(-8.5, 4, 3.6)
    for x in (0, 8.5):
        ic.circle(x, 4, 3.6, DASH)
    ic.arrow((-12, -5), (12, -5), length=3.4, half=2.4)
    return ic


def sketch_circular_pattern():
    ic = sketch_tool("circular-pattern")
    ic.circle(*polar(0, 0, 8, 90), 3.6)
    for degrees in (210, 330):
        ic.circle(*polar(0, 0, 8, degrees), 3.6, DASH)
    ic.node(0, 0)
    return ic


def sketch_project():
    """Project Curve: an edge of the part, brought down into the sketch."""
    ic = sketch_tool("project")
    ic.plate(-2, -2, 12, 12)
    ic.plate(1.5, 1.5, 8.5, 8.5)
    for x, y in ((8.5, 1.5), (1.5, 8.5)):
        ic.wire([(x, y, 0), (x, y, 7)], dash=DASH)
    ic.block(1.5, 1.5, 7, 8.5, 8.5, 11)
    return ic


def sketch_intersection():
    """Intersection Curve: where the part meets the sketch's plane."""
    ic = sketch_tool("intersection")
    ic.plate(-1, -1, 12, 12)
    ic.block(3.5, 3.5, 0, 9, 9, 4)
    return ic


def sketch_convert_reference():
    """Convert To/From Reference: a curve made a reference line, or back."""
    ic = sketch_tool("convert-reference")
    ic.line([(-12, 4), (0, -8)])
    ic.line([(0, 8), (12, -4)], dash=DASH)
    ic.arrow((-2, -2), (2, 2), length=2.8, half=2)
    ic.head((-2, -2), (2, 2), length=2.8, half=2)
    return ic


def finish_sketch():
    """The page, done: the tick above it."""
    ic = Icon("finish-sketch")
    ic.plate(0, 0, 13, 13)
    ic.line([(4.5, -6), (7.5, -3), (13.5, -10)])
    return ic


# The workspace's other tools: what each looks at or does, on the part.


SELECT_KINDS = ("all", "face", "edge", "face-group", "edge-group", "body", "part", "position")


def select(kind):
    """Select, and each of its filters: the pointer beside a block, the block marked with what it picks."""
    ic = Icon("select" if kind == "all" else f"select-{kind}")
    s, h = 9, 6
    tip = (7.5, 7.5)
    if kind == "part":
        # an assembly's part: the block on the plate, picked alone
        ic.block(-1, -1, 0, 11, 11, 2)
        ic.block(4, 4, 2, 10, 10, 6.5)
        ic.pointer((9, 8.5))
        return ic
    if kind == "position":
        # a joint's knob, taken to turn the part on it
        ic.block(0, 0, 0, s, s, 3)
        cx, cy = 0, -9
        ic.path(f"M{num(cx - 9)} {num(cy)} A9 4.5 0 0 0 {num(cx + 9)} {num(cy)}", [(cx - 9, cy), (cx, cy + 4.5)])
        ic.head((cx + 9.4, cy - 2.4), (cx + 8.8, cy + 2), length=3.4, half=2.4)
        ic.pointer((5, 4.5))
        return ic
    ic.block(0, 0, 0, s, s, h)
    top = ((0, 0, h), (s, 0, h), (0, s, h), (s, s, h))
    near = ic.P(s, s, h)
    if kind in ("face", "face-group"):
        ic.hatch(*top)
    if kind == "face-group":
        ic.hatch((0, s, h), (0, s, 0), (s, s, h), (s, s, 0), 1)
    if kind == "edge":
        ic.node(*ic.P(s, 0, h))
        ic.node(*near)
    if kind == "edge-group":
        for x, y in ((0, 0), (s, 0), (s, s), (0, s)):
            ic.node(*ic.P(x, y, h))
    if kind == "body":
        ic.hatch(*top, 1)
        ic.hatch((0, s, h), (0, s, 0), (s, s, h), (s, s, 0), 1)
        ic.hatch((s, s, h), (s, s, 0), (s, 0, h), (s, 0, 0), 1)
    ic.pointer(tip)
    return ic


MEASURE_KINDS = ("all", "vertex", "edge", "face")


def measure(kind):
    """Measure, and each of its filters: a distance over a block, the block marked with what it measures alone."""
    ic = Icon("measure" if kind == "all" else f"measure-{kind}")
    s, h = 11, 6
    ic.block(0, 0, 0, s, s, h)
    # the distance between two of its corners, measured over it
    dimension(ic, -9.5, -11, 11, -1.5)
    if kind == "face":
        ic.hatch((0, 0, h), (s, 0, h), (0, s, h), (s, s, h))
    elif kind == "edge":
        ic.node(*ic.P(0, s, h))
        ic.node(*ic.P(s, s, h))
    elif kind == "vertex":
        ic.node(*ic.P(s, s, h))
    return ic


def measure_bodies():
    """Measure Bodies: a body, and where its mass centres."""
    ic = Icon("measure-bodies")
    ic.block(0, 0, 0, 10, 10, 7)
    cx, cy, r = 9, -9, 4.4
    ic.circle(cx, cy, r)
    ic.line([(cx - r, cy), (cx + r, cy)])
    ic.line([(cx, cy - r), (cx, cy + r)])
    return ic


def draft_analysis():
    """Draft Analysis: a drafted body, a face hatched by how it draws against the pull above it."""
    ic = Icon("draft-analysis")
    b, a, h = 13, 3, 8
    frustum(ic, b, a, h)
    ic.hatch((a, b - a, h), (b - a, b - a, h), (0, b, 0), (b, b, 0))
    ic.arrow(ic.P(b / 2, b / 2, h), (0, -15))
    return ic


def section():
    """Edit Section: the part cut on a plane, what the cut shows hatched."""
    ic = Icon("section")
    s, h, cut = 13, 9, 8
    ic.block(0, 0, 0, cut, s, h)
    for c in (-3, 1.5, 6, 10.5):
        start = max(0, -c)
        end = min(h, s - c)
        ic.wire([(cut, c + start, h - start), (cut, c + end, h - end)])
    return ic


def exploded():
    """Exploded Views: an assembly's parts drawn apart, along the way they come off."""
    ic = Icon("exploded")
    ic.block(0, 0, 0, 12, 12, 3.5)
    lo, hi, z0 = 3, 9, 10
    for x, y in ((hi, lo), (lo, hi)):
        ic.wire([(x, y, 3.5), (x, y, z0)], dash=DASH)
    ic.block(lo, lo, z0, hi, hi, z0 + 4)
    return ic


def interference():
    """Simple Interference: two bodies, seen through, and the volume both fill hatched."""
    ic = Icon("interference")
    ic.line([(-12, -12), (4, -12), (4, 4), (-12, 4)], True)
    ic.line([(-4, -4), (12, -4), (12, 12), (-4, 12)], True)
    for a, b in (((-4, 0), (0, -4)), ((-4, 4), (4, -4)), ((0, 4), (4, 0))):
        ic.line([a, b])
    return ic


def compare():
    """Compare: the part as it is, seen from the front, and what it had before, dashed."""
    ic = Icon("compare")
    ic.line([(-12, 10), (-12, -8), (-3, -8), (-3, 3), (12, 3), (12, 10)], True)
    ic.line([(3, 3), (3, -8), (12, -8), (12, 3)], dash=DASH)
    return ic


def appearance():
    """Edit Object Display: the part's color: a ball, and a drop of what it is given."""
    ic = Icon("appearance")
    ic.circle(-3, 3, 9)
    ic.arc(-3, 3, 5.5, 100, 170)
    ic.path("M8 -12 C8 -12 3.6 -7 3.6 -4.2 A4.4 4.4 0 0 0 12.4 -4.2 C12.4 -7 8 -12 8 -12 Z", [(3.6, -12), (12.4, 0.2)])
    return ic


def orient_view():
    """Orient View: the plane picked, turned from where it is seen to square on to the view."""
    ic = Icon("orient-view")
    ic.line([(-12.5, 6.5), (-4.5, 2.5), (3.5, 6.5), (-4.5, 10.5)], True, DASH)
    ic.line([(-0.5, -11.5), (12.5, -11.5), (12.5, 1.5), (-0.5, 1.5)], True)
    ic.circle(6, -5, 2.6)
    ic.path("M-9.5 3 C-9.5 -2.5 -8 -5 -4.6 -5", [(-9.5, -5), (-9.5, 3)])
    ic.head((-3.6, -5), (-7, -5), length=3.4, half=2.6)
    return ic


def drawing():
    """A drawing's sheet, its title block, and the part's view."""
    ic = Icon("drawing")
    ic.line([(-12.5, -9.5), (12.5, -9.5), (12.5, 9.5), (-12.5, 9.5)], True)
    ic.line([(3, 9.5), (3, 4), (12.5, 4)])
    ic.block(0, 4.5, 6, 5, 9.5, 9.5)
    return ic


def turn(name, back):
    """Undo (`back`) and Redo: the change last made, turned back, or made again."""
    ic = Icon(name)
    cx, cy, r = 0, 2.5, 9
    # up over the top from below on one side, and down on the other, where the head points
    a0, a1 = (-35, 188) if back else (215, -8)
    steps = [a0 + (a1 - a0) * i / 24 for i in range(25)]
    arc = [polar(cx, cy, r, a) for a in steps]
    ic.line(arc)
    ic.head(arc[-1], arc[-4], length=5, half=3.6)
    return ic


def assembly_constraints():
    """Assembly Constraints: a part brought to another, its pin on the hole's axis."""
    ic = Icon("assembly-constraints")
    ic.block(0, 0, 0, 12, 12, 5)
    ic.hole(6, 6, 5, 3.6, 1.6)
    ic.line([ic.P(6, 6, 5), ic.P(6, 6, 11.2)], dash=DASH)
    ic.cylinder(6, 6, 13, 18, 3.4)
    ic.arrow((7, -13), (7, -5), length=3.4, half=2.4)
    return ic


def part():
    """A part: one body, a bracket with a hole."""
    ic = Icon("part")
    s, t = 13, 3
    bracket(ic, s, t, 11)
    ic.hole(8.5, 6.5, t, 2.8, 1.2)
    return ic


def assembly():
    """An assembly: parts placed together, the bracket and a pin in it."""
    ic = Icon("assembly")
    t = 3
    bracket(ic, 13, t, 11)
    ic.cylinder(8.5, 6.5, t, t + 4.2, 2.6)
    return ic


def move():
    """Move Object: the body where it was, dashed, and where it is now."""
    ic = Icon("move")
    s, h, d = 5, 5, 6.5
    ic.block(0, 0, 0, s, s, h, DASH)
    ic.block(d, -d, 0, d + s, s - d, h)
    y = ic.P(0, 0, h)[1] - 3.5
    ic.arrow((-4, y), (17, y))
    return ic


def expressions():
    """Expressions: a part's named values, a name equal to its value."""
    ic = Icon("expressions")
    ic.cross(-8.5, 0, 3.5)
    for y in (-2, 2):
        ic.line([(-2.5, y), (3, y)])
    ic.line([(6.5, -5), (12.5, -5), (12.5, 5), (6.5, 5)], True)
    return ic


# The agent's tools.


def add_context():
    """Add to context: the selection put into the chat box, to go with the next message."""
    ic = Icon("add-context")
    ic.path(BUBBLE, [(-12, -10), (12, 10.5)])
    ic.line([(-4.8, -2.25), (4.8, -2.25)])
    ic.line([(0, -7), (0, 2.5)])
    return ic


MARK = "M-13 10 Q-10 3 -7 7 T-1 5"


def annotate():
    """Annotate: a mark drawn on the part, and what drew it."""
    ic = Icon("annotate")
    ic.path(MARK, [(-13, 3), (-1, 10)])
    ic.pen((-1, 5))
    return ic


def highlighter():
    """Annotate's highlighter: a broad band, and its chisel."""
    ic = Icon("annotate-highlighter")
    ic.line([(-13, 12), (-13, 7), (-3, 7), (-3, 12)], True)
    ic.pen((-3, 5), width=7, chisel=True)
    return ic


def eraser():
    """Annotate's eraser: a mark taken off where it has been."""
    ic = Icon("annotate-eraser")
    ic.path(MARK, [(-13, 3), (-1, 10)], DASH)
    ic.rubber((-1, 7))
    return ic


SHAPE_KINDS = ("rectangle", "line", "arrow", "ellipse", "text")


def shape_mark(kind):
    """Each of Shapes' tools, as the mark it makes."""
    ic = Icon(f"shapes-{kind}")
    if kind == "rectangle":
        ic.line([(-10.5, -7.5), (10.5, -7.5), (10.5, 7.5), (-10.5, 7.5)], True)
    elif kind == "line":
        ic.line([(-10, 9), (10, -9)])
    elif kind == "arrow":
        ic.arrow((-10, 9), (10, -9))
    elif kind == "ellipse":
        ic.ellipse(0, 0, 11, 7.5)
    else:
        ic.line([(-8, -8), (8, -8)])
        ic.line([(0, -8), (0, 9)])
    return ic


def shapes():
    """Shapes: a box drawn, and an arrow at it."""
    ic = Icon("shapes")
    ic.line([(-12, -3), (3, -3), (3, 11), (-12, 11)], True)
    ic.arrow((13, -13), (6, -6))
    return ic


# Every icon, in the sprite's order, by the group the sheet shows it in: the set Amy approved, then
# what the workspace adds to it.
GROUPS = (
    ("Approved", "The modeling commands and the Part Navigator's features, as Amy approved them; the check is a status mark.", (
        sketch, extrude, revolve, hole, lambda: rounded("blend"), lambda: rounded("chamfer"), shell, draft, rib,
        pattern, mirror, datum_plane, csys, sweep, loft, split, delete, body, offset_face, delete_face, ask,
    )),
    ("The agent's tools", "Beside Ask: Add to context; Annotate (the Pencil) with its pen, "
     "highlighter and eraser; Shapes, and each shape it draws.", (
        add_context, annotate, highlighter, eraser, shapes, *((lambda kind=kind: shape_mark(kind)) for kind in SHAPE_KINDS),
    )),
    ("The workspace's tools", "The strip's tools, the Analysis, View, Assemblies and Drafting tabs, Expressions, "
     "and Undo and Redo.", (
        lambda: select("all"), lambda: measure("all"), section, exploded, measure_bodies, draft_analysis, interference,
        compare, appearance, orient_view, drawing, assembly_constraints, expressions,
        lambda: turn("undo", back=True), lambda: turn("redo", back=False),
    )),
    ("Select's and Measure's filters", "What each picks alone, marked on the block, and how Select grows a pick.", (
        *((lambda kind=kind: select(kind)) for kind in SELECT_KINDS if kind != "all"),
        *((lambda kind=kind: measure(kind)) for kind in MEASURE_KINDS if kind != "all"),
    )),
    ("The Part Navigator's rows", "A part, an assembly, and Move Object.", (part, assembly, move)),
    ("The sketch tools", "Finish Sketch, each tool of the sketch task environment in its order, and Convert To/From Reference.", (
        finish_sketch, sketch_line, sketch_rectangle, sketch_center_rectangle, sketch_three_point_rectangle, sketch_circle,
        sketch_three_point_circle, sketch_arc, sketch_three_point_arc, sketch_tangent_arc, sketch_slot, sketch_center_slot,
        sketch_polygon, sketch_spline, sketch_reference_line, sketch_point, sketch_dimension, lambda: corner("fillet"),
        lambda: corner("chamfer"), sketch_trim, sketch_extend, sketch_offset, sketch_mirror, sketch_move, sketch_copy,
        sketch_rotate, sketch_scale, sketch_linear_pattern, sketch_circular_pattern, sketch_project, sketch_intersection,
        sketch_convert_reference,
    )),
)
ICONS = tuple(make for _, _, makers in GROUPS for make in makers)


def symbols():
    """The sprite's symbols in order, as (name, markup): the check, then each icon drawn."""
    return [("check", CHECK)] + [(ic.name, ic.symbol()) for ic in (make() for make in ICONS)]


def sprite(drawn=None):
    """The hidden <svg> of <symbol>s, for a page to paste in."""
    return "\n".join(
        ['<svg width="0" height="0" style="position:absolute" aria-hidden="true">']
        + [markup for _, markup in drawn or symbols()]
        + ["</svg>"]
    )


def react_attribute(name):
    """An SVG attribute as React spells it: stroke-width is strokeWidth; aria-* keeps its hyphen."""
    return name if name.startswith("aria-") else re.sub(r"-([a-z])", lambda match: match.group(1).upper(), name)


def quote(value):
    """An attribute's value as JSX writes it between double quotes."""
    return value.replace("&", "&amp;").replace('"', "&quot;")


def jsx(element, depth):
    """An element as JSX lines, one element to a line, `depth` levels in."""
    if (element.text or "").strip() or (element.tail or "").strip():
        raise ValueError(f"<{element.tag}> holds text; the icons are drawn with elements alone")
    pad = "  " * depth
    attrs = "".join(f' {react_attribute(name)}="{quote(value)}"' for name, value in element.attrib.items())
    if not len(element):
        return [f"{pad}<{element.tag}{attrs} />"]
    inner = [line for child in element for line in jsx(child, depth + 1)]
    return [f"{pad}<{element.tag}{attrs}>", *inner, f"{pad}</{element.tag}>"]


MODULE = """\
// Generated by scripts/nx-icons.py --jsx. To change an icon, change the generator and run it again;
// never edit this file.
//
// The CAD workspace's icons, line glyphs in the text's own color: one hidden SVG sprite (NxIconSprite),
// mounted once, and NxIcon, which draws one of its symbols by name. Every id in the sprite starts with "@PREFIX@".

/** The name of every icon in the sprite: what NxIcon takes. */
export const NX_ICON_NAMES = Object.freeze([
@NAMES@
]);

// Made once, so that however often NxIconSprite is rendered, React is handed the same element and leaves it be.
const SPRITE = (
  <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
@SPRITE@
  </svg>
);

/**
 * The icons' symbols, hidden. Mount it once in the page: every NxIcon draws from it.
 */
export function NxIconSprite() {
  return SPRITE;
}

/**
 * One icon of the sprite, by name. Its symbol's own viewBox fits it to the box `className` gives the
 * svg, so the class sets its size, and its lines take the color of the text around it, as with the
 * other icons.
 */
export function NxIcon({ name, className }) {
  return <svg className={className} aria-hidden="true" focusable="false"><use href={`#@PREFIX@${name}`} /></svg>;
}
"""


def module():
    """The viewer's module: the icons' names, the sprite as a component, and NxIcon."""
    drawn = symbols()
    markup = [symbol for _, symbol in drawn]
    values = {
        "PREFIX": PREFIX,
        "NAMES": "\n".join(f'  "{name}",' for name, _ in drawn),
        "SPRITE": "\n".join(line for part in markup for line in jsx(ElementTree.fromstring(part), 2)),
    }
    return re.sub(r"@([A-Z]+)@", lambda match: values[match.group(1)], MODULE)


SHEET_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio CAD icons</title>
<style>
:root { --page: #f6f7f9; --ink: #1f2328; --muted: #5e6672; --card: #ffffff; --rule: #e3e6ea; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --page: #1c1d20; --ink: #e8eaed; --muted: #a2a9b3; --card: #26282c; --rule: #3a3d42; }
}
:root[data-theme="dark"] { --page: #1c1d20; --ink: #e8eaed; --muted: #a2a9b3; --card: #26282c; --rule: #3a3d42; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px 48px; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1180px; margin: 0 auto; }
h1 { margin: 0 0 4px; font-size: 20px; font-weight: 600; }
h2 { margin: 32px 0 2px; font-size: 15px; font-weight: 600; }
p { margin: 0; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 8px; margin-top: 12px; }
figure { margin: 0; background: var(--card); border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; }
.sizes { display: flex; align-items: center; justify-content: space-evenly; height: 48px; }
.light { background: #ffffff; color: #4b5563; }
.dark { background: #27292d; color: #c9ced6; }
figcaption { padding: 6px 8px; font-size: 12px; border-top: 1px solid var(--rule); overflow-wrap: anywhere; }
</style>
</head>
<body>
@SPRITE@
<main>
<h1>Studio's CAD icons</h1>
<p>Every icon scripts/nx-icons.py draws, at 16, 24 and 32 px, on the viewer's light and dark backgrounds.</p>
@GROUPS@
</main>
</body>
</html>
"""


def sheet_page():
    """A page of every icon by group, each named, at 16, 24 and 32 px on light and on dark."""
    drawn = symbols()

    def card(name):
        tiles = "".join(
            f'<div class="sizes {theme}">' + "".join(
                f'<svg width="{size}" height="{size}" aria-hidden="true"><use href="#{PREFIX}{name}"/></svg>' for size in (16, 24, 32)
            ) + "</div>" for theme in ("light", "dark")
        )
        return f"<figure>{tiles}<figcaption>{html.escape(name)}</figcaption></figure>"

    names = iter(name for name, _ in drawn)
    check = next(names)  # the sprite's status mark, shown with the set it came with
    sections = []
    for index, (title, about, makers) in enumerate(GROUPS):
        group = ([check] if index == 0 else []) + [next(names) for _ in makers]
        sections.append(f"<section><h2>{html.escape(title)}</h2><p>{html.escape(about)}</p>"
                        f'<div class="grid">{"".join(card(name) for name in group)}</div></section>')
    return SHEET_PAGE.replace("@SPRITE@", sprite(drawn)).replace("@GROUPS@", "\n".join(sections))


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as out:
        out.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jsx", metavar="OUT", nargs="?", const=MODULE_PATH,
                        help="write the viewer's module (src/lib/nxIcons.generated.jsx, or OUT) instead of printing the sprite")
    parser.add_argument("--sheet", metavar="OUT", help="write a page of every icon at 16, 24 and 32 px, on light and on dark")
    args = parser.parse_args(argv)
    if args.jsx:
        write(args.jsx, module())
    if args.sheet:
        write(args.sheet, sheet_page())
    if not args.jsx and not args.sheet:
        print(sprite())


if __name__ == "__main__":
    main()
