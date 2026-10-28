#!/usr/bin/env python3
"""Studio's NX-style icons, drawn from 3D on one isometric grid.

Every icon is built from boxes, cylinders and faces in model space, projected the same way
(2:1 isometric, 1 unit = 1 px at 32 px) and lit the same way (top lightest, the side facing +y
mid, the side facing +x darkest), in flat tones of five materials: yellow-orange for what a feature
makes (and what a pick takes), gray for the body it works on, blue for sketches, planes and
directions, tan for datums, purple for the agent. A sketch tool is drawn flat, in the sketch's
blue, as NX draws its curve tools: its curves, and white handles where its clicks go. Outlines stay
1 px at every size. Red, amber and green say how something went, so no icon wears them: the check
is a status mark, not an icon.

With no arguments it prints the hidden <svg> of <symbol>s the mockup uses. `--jsx [OUT]` writes the
viewer's module instead (src/lib/nxIcons.generated.jsx unless OUT is given): the sprite as a
component, the icons' names, and NxIcon, which draws one by name. `--sheet OUT` writes a page of
every icon, named, at 16, 24 and 32 px on light and on dark, the set Amy approved first. Run it
again whenever an icon changes. Every id is "nx-" and the icon's name, so nothing collides with the
page the sprite is mounted in.
"""

import argparse
import html
import math
import os
import re
import sys
from xml.etree import ElementTree

FEAT = dict(top="#FFD660", mid="#FAC44B", slope="#F4BC48", left="#F6B337", right="#E29620", edge="#A9620A")
BODY = dict(top="#F4F6F9", left="#D3DAE2", right="#AFB9C5", edge="#66727F")
TAN = dict(top="#F8E7C4", left="#EFD6A6", right="#E4C287", edge="#B5853A")
GHOST = dict(top="#FFEBC0", left="#FCDDA2", right="#F7CF86", edge="#CF9235")
BLUE, BLUE_FILL, DARK = "#2F73D9", "#DFEBFC", "#39424D"
PURPLE, PURPLE_FILL = "#7C3AED", "#F1EAFE"
# The agent's purple as a material, for what it draws with (Annotate's marker).
AGENT = dict(top="#C9AEFB", left="#A47AF6", right="#8B55F0", edge="#5B21B6")
# Faces as Draft Analysis shades them against the pull, in the direction's blue.
DRAWS = dict(left="#C4D8F6", right="#94B6EA")
DASH = "2.2 1.6"
CURVE, REFERENCE = 1.8, 1.3  # a sketch curve's width, and a reference line's, dashed
GHOSTLY = 0.6  # the opacity of a sketch's ghost: what a tool takes away, or what was there before
PREFIX = "nx-"  # on every id this writes: symbols, gradients, clip paths
FSIDE = f"{PREFIX}fside"  # the gradients the icons share: the side of a cylinder a feature makes,
BSIDE = f"{PREFIX}bside"  # and of one the body has
MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "lib", "nxIcons.generated.jsx")

SHARED = (
    f'<linearGradient id="{FSIDE}" x1="0" y1="0" x2="1" y2="0">'
    '<stop offset="0" stop-color="#F9BE45"/><stop offset=".55" stop-color="#EFA72D"/>'
    '<stop offset="1" stop-color="#DC8E1A"/></linearGradient>'
    f'<linearGradient id="{BSIDE}" x1="0" y1="0" x2="1" y2="0">'
    f'<stop offset="0" stop-color="{BODY["left"]}"/><stop offset="1" stop-color="{BODY["right"]}"/></linearGradient>'
)
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


def edge(color, dash=None):
    """A line that stays 1 px at every size."""
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'fill="none" stroke="{color}" stroke-width="1" stroke-linejoin="round" '
        f'stroke-linecap="round" vector-effect="non-scaling-stroke"{extra}'
    )


class Icon:
    def __init__(self, name):
        self.name, self.id, self.parts, self.defs, self.pts = name, PREFIX + name, [], [], []

    @staticmethod
    def P(x, y, z):
        return (x - y, (x + y) / 2 - z)

    def proj(self, pts3):
        return [self.P(*p) for p in pts3]

    @staticmethod
    def d(pts, closed=True):
        return "M" + " L".join(f"{num(x)} {num(y)}" for x, y in pts) + (" Z" if closed else "")

    def raw(self, svg, pts=()):
        self.pts += list(pts)
        self.parts.append(svg)

    def shape(self, pts, fill, extra=""):
        self.raw(f'<path d="{self.d(pts)}" fill="{fill}"{extra}/>', pts)

    def face(self, pts3, fill, extra=""):
        self.shape(self.proj(pts3), fill, extra)

    def outline(self, pts, color, closed=True, dash=None):
        self.raw(f'<path d="{self.d(pts, closed)}" {edge(color, dash)}/>', pts)

    def stroke(self, pts, color=BLUE, width=1.6, dash=None):
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.raw(
            f'<path d="{self.d(pts, False)}" fill="none" stroke="{color}" stroke-width="{num(width)}" '
            f'stroke-linecap="round" stroke-linejoin="round"{extra}/>',
            pts,
        )

    def head(self, tip, behind, color=BLUE, length=4.4, half=2.5):
        """An arrowhead at tip, pointing away from behind; returns where its shaft should end."""
        dx, dy = tip[0] - behind[0], tip[1] - behind[1]
        n = math.hypot(dx, dy)
        ux, uy = dx / n, dy / n
        bx, by = tip[0] - ux * length, tip[1] - uy * length
        self.shape([tip, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)], color)
        return (bx + ux * 0.8, by + uy * 0.8)

    def arrow(self, start, tip, color=BLUE, width=1.6, length=4.4, half=2.5):
        self.stroke([start, self.head(tip, start, color, length, half)], color, width)

    def clip(self, pts):
        cid = f"{self.id}-c{len(self.defs)}"
        self.defs.append(f'<clipPath id="{cid}"><path d="{self.d(pts)}"/></clipPath>')
        return cid

    def gradient(self, p0, p1, stops):
        gid = f"{self.id}-g{len(self.defs)}"
        s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
        self.defs.append(
            f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{num(p0[0])}" y1="{num(p0[1])}" '
            f'x2="{num(p1[0])}" y2="{num(p1[1])}">{s}</linearGradient>'
        )
        return f"url(#{gid})"

    def box(self, x0, y0, z0, x1, y1, z1, m, outline=True):
        P = self.P
        sil = [P(x0, y0, z1), P(x1, y0, z1), P(x1, y0, z0), P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1)]
        self.shape(sil, m["right"])
        self.face([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], m["top"])
        self.face([(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)], m["left"])
        self.face([(x1, y0, z1), (x1, y1, z1), (x1, y1, z0), (x1, y0, z0)], m["right"])
        if outline:
            self.outline(sil, m["edge"])
        return sil

    def cylinder(self, x, y, z0, z1, r, m=FEAT, side=f"url(#{FSIDE})"):
        """An upright cylinder; r is its radius on screen."""
        cx, top = self.P(x, y, z1)
        _, bottom = self.P(x, y, z0)
        ry = r / 2
        L, R, T, B, rr = num(cx - r), num(cx + r), num(top), num(bottom), f"{num(r)} {num(ry)}"
        self.raw(
            f'<path d="M{L} {T} L{L} {B} A{rr} 0 0 0 {R} {B} L{R} {T} Z" fill="{side}"/>',
            [(cx - r, top - ry), (cx + r, bottom + ry)],
        )
        self.raw(f'<ellipse cx="{num(cx)}" cy="{T}" rx="{num(r)}" ry="{num(ry)}" fill="{m["top"]}"/>')
        self.raw(f'<path d="M{L} {T} L{L} {B} A{rr} 0 0 0 {R} {B} L{R} {T} A{rr} 0 0 0 {L} {T}" {edge(m["edge"])}/>')

    def hole(self, x, y, z, r, depth, wall=FEAT["right"], rim=FEAT["edge"]):
        cx, cy = self.P(x, y, z)
        e = f'cx="{num(cx)}" cy="{num(cy)}" rx="{num(r)}" ry="{num(r / 2)}"'
        cid = f"{self.id}-c{len(self.defs)}"
        self.defs.append(f'<clipPath id="{cid}"><ellipse {e}/></clipPath>')
        self.raw(f'<ellipse {e} fill="{wall}"/>')
        self.raw(
            f'<ellipse cx="{num(cx)}" cy="{num(cy + depth)}" rx="{num(r)}" ry="{num(r / 2)}" '
            f'fill="{DARK}" clip-path="url(#{cid})"/>'
        )
        self.raw(f'<ellipse {e} {edge(rim)}/>')

    def pencil(self, tip, length=14.5, width=5.0):
        ux, uy = math.sqrt(0.5), -math.sqrt(0.5)  # from the tip toward the end
        nx, ny = -uy, ux  # across, toward the shaded side

        def at(s, k):
            return (tip[0] + ux * s + nx * k * width / 2, tip[1] + uy * s + ny * k * width / 2)

        cone, end, lead = 5.0, length - 2.8, 1.9
        self.shape([tip, at(cone, -1), at(cone, 1)], "#F6DFB9")
        self.shape([tip, at(lead, -lead / cone), at(lead, lead / cone)], DARK)
        for k0, k1, tone in ((-1, -1 / 3, FEAT["top"]), (-1 / 3, 1 / 3, FEAT["left"]), (1 / 3, 1, FEAT["right"])):
            self.shape([at(cone, k0), at(end, k0), at(end, k1), at(cone, k1)], tone)
        self.shape([at(end, -1), at(length, -1), at(length, 1), at(end, 1)], "#C9D1DA")
        self.outline([tip, at(cone, -1), at(length, -1), at(length, 1), at(cone, 1)], FEAT["edge"])

    def marker(self, tip, length=13, width=4.6, chisel=False):
        """The agent's marker, drawing at tip: Annotate's, in the agent's purple; `chisel`, the highlighter's broad nib."""
        ux, uy = math.sqrt(0.5), -math.sqrt(0.5)
        nx, ny = -uy, ux

        def at(s, k):
            return (tip[0] + ux * s + nx * k * width / 2, tip[1] + uy * s + ny * k * width / 2)

        nib, cap = 3.6, length - 3
        # the nib: a point, or the chisel's flat, slanted edge
        nose = [at(0, -0.55), at(1.4, 0.55)] if chisel else [tip]
        self.shape(nose + [at(nib, 0.55), at(nib, -0.55)], PURPLE)
        for k0, k1, tone in ((-1, -1 / 3, AGENT["top"]), (-1 / 3, 1 / 3, AGENT["left"]), (1 / 3, 1, AGENT["right"])):
            self.shape([at(nib, k0 * 0.55), at(nib + 1.6, k0), at(cap, k0), at(cap, k1), at(nib + 1.6, k1), at(nib, k1 * 0.55)], tone)
        self.shape([at(cap, -1), at(length, -1), at(length, 1), at(cap, 1)], PURPLE)
        self.outline(nose[:1] + [at(nib, -0.55), at(nib + 1.6, -1), at(length, -1), at(length, 1), at(nib + 1.6, 1), at(nib, 0.55)] + nose[1:],
                     AGENT["edge"])

    def rubber(self, tip, length=11, width=7.4):
        """The agent's eraser, rubbing at tip: a block of white rubber in a purple sleeve."""
        ux, uy = math.sqrt(0.5), -math.sqrt(0.5)
        nx, ny = -uy, ux

        def at(s, k):
            return (tip[0] + ux * s + nx * k * width / 2, tip[1] + uy * s + ny * k * width / 2)

        sleeve = 5
        self.shape([at(0, -1), at(sleeve, -1), at(sleeve, 1), at(0, 1)], "#fff")
        for k0, k1, tone in ((-1, -1 / 3, AGENT["top"]), (-1 / 3, 1 / 3, AGENT["left"]), (1 / 3, 1, AGENT["right"])):
            self.shape([at(sleeve, k0), at(length, k0), at(length, k1), at(sleeve, k1)], tone)
        self.outline([at(0, -1), at(length, -1), at(length, 1), at(0, 1)], AGENT["edge"])
        self.stroke([at(sleeve, -1), at(sleeve, 1)], AGENT["edge"], width=1)

    def pointer(self, tip):
        """The pointer, its tip at `tip`: what Select picks with."""
        x, y = tip
        arrow = [(x, y), (x, y + 10.6), (x + 2.7, y + 8.1), (x + 4.5, y + 12.2), (x + 6.4, y + 11.4), (x + 4.6, y + 7.4), (x + 8.2, y + 7.4)]
        self.shape(arrow, "#fff")
        self.outline(arrow, DARK)

    # A sketch tool is drawn flat, in screen units: curves in the sketch's blue, regions filled pale,
    # and a white handle where each click goes.

    def handle(self, x, y, s=2):
        """Where a click goes: a white square edged in the sketch's blue."""
        box = [(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)]
        self.shape(box, "#fff")
        self.outline(box, BLUE)

    def curve(self, d, extent, width=CURVE, dash=None, color=BLUE, fill="none", opacity=None):
        """A sketch curve along the path `d`; `extent`, points its box must hold."""
        extra = (f' stroke-dasharray="{dash}"' if dash else "") + (f' opacity="{num(opacity)}"' if opacity else "")
        self.raw(
            f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{num(width)}" stroke-linecap="round" '
            f'stroke-linejoin="round"{extra}/>',
            extent,
        )

    def region(self, pts, width=CURVE, ghost=False):
        """A closed sketch curve through `pts`, filled pale; a ghost, dashed and faint."""
        self.curve(self.d(pts), pts, width, DASH if ghost else None, fill="none" if ghost else BLUE_FILL, opacity=GHOSTLY if ghost else None)

    def circle(self, cx, cy, r, width=CURVE, ghost=False, fill=BLUE_FILL, dash=None):
        self.curve(f"M{num(cx - r)} {num(cy)} A{num(r)} {num(r)} 0 1 0 {num(cx + r)} {num(cy)} A{num(r)} {num(r)} 0 1 0 "
                   f"{num(cx - r)} {num(cy)} Z", [(cx - r, cy - r), (cx + r, cy + r)], width, DASH if ghost else dash,
                   fill="none" if ghost else fill, opacity=GHOSTLY if ghost else None)

    def arc(self, cx, cy, r, a0, a1, width=CURVE, dash=None):
        """An arc turning anticlockwise on screen from a0 to a1 degrees; returns its ends."""
        start, end = polar(cx, cy, r, a0), polar(cx, cy, r, a1)
        large = 1 if (a1 - a0) % 360 > 180 else 0
        extent = [polar(cx, cy, r, a0 + (a1 - a0) * i / 8) for i in range(9)]
        self.curve(f"M{num(start[0])} {num(start[1])} A{num(r)} {num(r)} 0 {large} 0 {num(end[0])} {num(end[1])}", extent, width, dash)
        return start, end

    def symbol(self, size=32):
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        print(f"{self.name}: {w:.1f} x {h:.1f}", file=sys.stderr)
        dx, dy = round(size - min(xs) - max(xs)) / 2, round(size - min(ys) - max(ys)) / 2
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (
            f'<symbol id="{self.id}" viewBox="0 0 {size} {size}">{defs}'
            f'<g transform="translate({num(dx)} {num(dy)})">{"".join(self.parts)}</g></symbol>'
        )


def sketch():
    ic = Icon("sketch")
    plane = ic.proj([(0, 0, 0), (12, 0, 0), (12, 12, 0), (0, 12, 0)])
    ic.shape(plane, BLUE_FILL)
    ic.outline(plane, BLUE)
    # a profile with a round end, being drawn from its back corner
    arc = [(6 + 3 * math.cos(math.radians(a)), 6 + 3 * math.sin(math.radians(a)), 0) for a in range(0, 181, 10)]
    ic.stroke(ic.proj([(3, 3, 0), (9, 3, 0)] + arc + [(3, 3, 0)]), width=1.6)
    ic.pencil(ic.P(3, 3, 0))
    return ic


def extrude():
    ic = Icon("extrude")
    plane = ic.proj([(-2, -2, 0), (12, -2, 0), (12, 12, 0), (-2, 12, 0)])
    ic.shape(plane, BLUE_FILL)
    ic.outline(plane, BLUE)
    ic.box(0, 0, 0, 10, 10, 9, FEAT)
    start = ic.P(5, 5, 9)
    ic.arrow(start, (start[0], start[1] - 9.5))
    return ic


def revolve():
    ic = Icon("revolve")
    ic.cylinder(0, 0, 0, 4, 11)
    ic.cylinder(0, 0, 4, 9.5, 5.2)
    top = ic.P(0, 0, 9.5)
    ic.stroke([top, (0, top[1] - 7.5)], width=1.3, dash=DASH)
    ic.stroke([(0, 6.5), (0, 9.5)], width=1.3, dash=DASH)
    # a turn around the axis, above the part
    cy, rx, ry = top[1] - 5, 6, 3
    arc = [(rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in range(165, -36, -5)]
    ic.stroke(arc[:-5], width=1.3)
    ic.head(arc[-1], arc[-5], length=3.6, half=2.1)
    return ic


def hole():
    ic = Icon("hole")
    ic.box(0, 0, 0, 12, 12, 8, BODY)
    ic.hole(6, 6, 8, 5.4, 3.4)
    return ic


def rounded(kind):
    """A block with its top front-left edge blended or chamfered: that edge is the feature."""
    ic = Icon(kind)
    s, h, r = 12, 9, 4.5
    P = ic.P
    if kind == "blend":
        steps = [i * math.pi / 16 for i in range(9)]

        def prof(x):
            return [(x, s - r + r * math.sin(t), h - r + r * math.cos(t)) for t in steps]
    else:

        def prof(x):
            return [(x, s - r, h), (x, s, h - r)]

    sil = [P(0, 0, h), P(s, 0, h), P(s, 0, 0), P(s, s, 0), P(0, s, 0)] + ic.proj(prof(0)[::-1])
    ic.shape(sil, BODY["right"])
    ic.face([(0, 0, h), (s, 0, h), (s, s - r, h), (0, s - r, h)], BODY["top"])
    ic.face([(0, s, h - r), (s, s, h - r), (s, s, 0), (0, s, 0)], BODY["left"])
    ic.face([(s, 0, h), (s, 0, 0), (s, s, 0)] + prof(s)[::-1], BODY["right"])
    ic.outline(sil, BODY["edge"])
    band = prof(0) + prof(s)[::-1]
    if kind == "blend":
        fill = ic.gradient(P(s / 2, s - r, h), P(s / 2, s, h - r), [(0, FEAT["top"]), (1, FEAT["left"])])
    else:
        fill = FEAT["mid"]
    ic.face(band, fill)
    ic.outline(ic.proj(band), FEAT["edge"])
    return ic


def shell():
    ic = Icon("shell")
    s, h, t = 13, 8, 1.6
    sil = ic.box(0, 0, 0, s, s, h, FEAT, outline=False)
    opening = ic.proj([(t, t, h), (s - t, t, h), (s - t, s - t, h), (t, s - t, h)])
    ic.raw(f'<g clip-path="url(#{ic.clip(opening)})">')
    ic.face([(t, t, t), (s - t, t, t), (s - t, s - t, t), (t, s - t, t)], "#F2B944")
    ic.face([(t, t, h), (s - t, t, h), (s - t, t, t), (t, t, t)], "#E9A12A")
    ic.face([(t, t, h), (t, s - t, h), (t, s - t, t), (t, t, t)], "#CF8410")
    ic.raw("</g>")
    ic.outline(opening, FEAT["edge"])
    ic.outline(sil, FEAT["edge"])
    return ic


def draft():
    ic = Icon("draft")
    b, a, h = 12, 2.6, 9
    P = ic.P
    sil = [P(a, a, h), P(b - a, a, h), P(b, 0, 0), P(b, b, 0), P(0, b, 0), P(a, b - a, h)]
    ic.shape(sil, FEAT["right"])
    ic.face([(a, a, h), (b - a, a, h), (b - a, b - a, h), (a, b - a, h)], FEAT["top"])
    ic.face([(a, b - a, h), (b - a, b - a, h), (b, b, 0), (0, b, 0)], "#F8BC42")
    ic.face([(b - a, a, h), (b - a, b - a, h), (b, b, 0), (b, 0, 0)], "#E9A12B")
    ic.outline(sil, FEAT["edge"])
    # the pull direction, and the draft angle from it
    foot = P(b, 0, 0)
    ic.stroke([foot, (foot[0], foot[1] - 12)], width=1.2, dash=DASH)
    r = 7.5
    up = (foot[0], foot[1] - r)
    tx, ty = P(b - a, a, h)
    n = math.hypot(tx - foot[0], ty - foot[1])
    along = (foot[0] + (tx - foot[0]) / n * r, foot[1] + (ty - foot[1]) / n * r)
    ic.raw(
        f'<path d="M{num(up[0])} {num(up[1])} A{num(r)} {num(r)} 0 0 0 {num(along[0])} {num(along[1])}" '
        f'fill="none" stroke="{BLUE}" stroke-width="1.2"/>',
        [up, along],
    )
    return ic


def rib():
    ic = Icon("rib")
    s, t, H = 12, 2, 12
    P = ic.P
    # one L-shaped body: a base plate and a wall along its back
    sil = [P(0, 0, H), P(t, 0, H), P(t, 0, t), P(s, 0, t), P(s, 0, 0), P(s, s, 0), P(0, s, 0), P(0, s, H)]
    ic.shape(sil, BODY["right"])
    ic.face([(0, 0, H), (t, 0, H), (t, s, H), (0, s, H)], BODY["top"])
    ic.face([(t, 0, t), (s, 0, t), (s, s, t), (t, s, t)], BODY["top"])
    ic.face([(t, 0, H), (t, s, H), (t, s, t), (t, 0, t)], BODY["right"])
    ic.face([(s, 0, t), (s, s, t), (s, s, 0), (s, 0, 0)], BODY["right"])
    ic.face([(0, s, 0), (s, s, 0), (s, s, t), (t, s, t), (t, s, H), (0, s, H)], BODY["left"])
    ic.outline(sil, BODY["edge"])
    # the rib, in the corner
    y0, y1, top, run = 5, 7, 10.5, 10.5
    ic.face([(t, y1, t), (run, y1, t), (t, y1, top)], FEAT["left"])
    ic.face([(t, y0, top), (t, y1, top), (run, y1, t), (run, y0, t)], FEAT["slope"])
    ic.outline(ic.proj([(t, y0, top), (run, y0, t), (run, y1, t), (t, y1, t), (t, y1, top)]), FEAT["edge"])
    return ic


def pattern():
    ic = Icon("pattern")
    s = 13
    ic.box(0, 0, 0, s, s, 2, BODY)
    for x, y in ((3.4, 3.4), (3.4, 9.6), (9.6, 3.4), (9.6, 9.6)):
        ic.cylinder(x, y, 2, 6.5, 2.8)
    return ic


def mirror():
    ic = Icon("mirror")
    # the copy, behind the mirror plane
    for pts, tone in (
        ([(4.5, 2, 7), (4.5, 10, 7), (4.5, 10, 0), (4.5, 2, 0)], GHOST["right"]),
        ([(0, 2, 3), (4.5, 2, 7), (4.5, 10, 7), (0, 10, 3)], GHOST["top"]),
        ([(0, 10, 3), (4.5, 10, 7), (4.5, 10, 0), (0, 10, 0)], GHOST["left"]),
    ):
        ic.face(pts, tone)
    ghost = ic.proj([(0, 2, 3), (4.5, 2, 7), (4.5, 2, 0), (4.5, 10, 0), (0, 10, 0), (0, 10, 3)])
    ic.outline(ghost, GHOST["edge"], dash="1.6 1.4")
    plane = ic.proj([(6, 0.5, -0.5), (6, 11.5, -0.5), (6, 11.5, 9.5), (6, 0.5, 9.5)])
    ic.shape(plane, BLUE_FILL, ' fill-opacity=".8"')
    ic.outline(plane, BLUE, dash=DASH)
    # the original, in front
    sil = ic.proj([(7.5, 2, 7), (12, 2, 3), (12, 2, 0), (12, 10, 0), (7.5, 10, 0), (7.5, 10, 7)])
    ic.shape(sil, FEAT["right"])
    ic.face([(7.5, 2, 7), (12, 2, 3), (12, 10, 3), (7.5, 10, 7)], FEAT["slope"])
    ic.face([(7.5, 10, 7), (12, 10, 3), (12, 10, 0), (7.5, 10, 0)], FEAT["left"])
    ic.face([(12, 2, 3), (12, 10, 3), (12, 10, 0), (12, 2, 0)], FEAT["right"])
    ic.outline(sil, FEAT["edge"])
    return ic


def datum_plane():
    ic = Icon("plane")
    plane = ic.proj([(0, 0, 0), (13, 0, 0), (13, 13, 0), (0, 13, 0)])
    ic.shape(plane, TAN["top"])
    ic.outline(plane, TAN["edge"])
    c = ic.P(6.5, 6.5, 0)
    ic.arrow(c, (c[0], c[1] - 12.5))
    return ic


def csys():
    ic = Icon("csys")
    a = 8.5
    for pts, tone in (
        ([(0, 0, 0), (a, 0, 0), (a, 0, a), (0, 0, a)], TAN["left"]),
        ([(0, 0, 0), (0, a, 0), (0, a, a), (0, 0, a)], TAN["right"]),
        ([(0, 0, 0), (a, 0, 0), (a, a, 0), (0, a, 0)], TAN["top"]),
    ):
        ic.face(pts, tone)
        ic.outline(ic.proj(pts), TAN["edge"])
    o = ic.P(0, 0, 0)
    for end in ((13, 0, 0), (0, 13, 0), (0, 0, 13)):
        ic.arrow(o, ic.P(*end), width=1.4, length=3.8, half=2.1)
    return ic


def sweep():
    ic = Icon("sweep")
    d = "M-11 8 C-4 8 2 -6 11 -6"
    ic.raw(f'<path d="{d}" fill="none" stroke="{FEAT["edge"]}" stroke-width="7.6"/>', [(-11, 4.2), (11, -9.8), (-11, 11.8), (11, -2.2)])
    ic.raw(f'<path d="{d}" fill="none" stroke="{FEAT["left"]}" stroke-width="5.6"/>')
    ic.raw(f'<path d="{d}" fill="none" stroke="{FEAT["top"]}" stroke-width="2" transform="translate(-.4 -1.5)"/>')
    ic.raw(f'<path d="{d}" fill="none" stroke="{BLUE}" stroke-width="1.1" stroke-dasharray="{DASH}"/>')
    ic.raw(f'<path d="M11 -9.8 V-2.2" {edge(FEAT["edge"])}/>')
    ic.raw(f'<ellipse cx="-11" cy="8" rx="1.9" ry="3.8" fill="{FEAT["top"]}"/>', [(-12.9, 4.2)])
    ic.raw(f'<ellipse cx="-11" cy="8" rx="1.9" ry="3.8" {edge(FEAT["edge"])}/>')
    return ic


def loft():
    ic = Icon("loft")
    fill = ic.gradient((0, -10), (0, 13), [(0, FEAT["top"]), (1, FEAT["right"])])
    top, bottom = "M-9 -1 C-3 -2.5 3 -9.5 9 -10", "M9 2 C3 2.5 -3 11 -9 13"
    ic.raw(f'<path d="{top} L9 2 C3 2.5 -3 11 -9 13 Z" fill="{fill}"/>', [(-9, -10), (9, 13)])
    ic.raw(f'<path d="{top} {bottom}" {edge(FEAT["edge"])}/>')
    ic.raw(
        f'<rect x="6.6" y="-10" width="4.8" height="12" rx="1.6" fill="none" stroke="{BLUE}" stroke-width="1.5"/>',
        [(6.6, -10), (11.4, 2)],
    )
    ic.raw(
        f'<ellipse cx="-9" cy="6" rx="3.2" ry="7" fill="{BLUE_FILL}" stroke="{BLUE}" stroke-width="1.5"/>',
        [(-12.2, -1), (-5.8, 13)],
    )
    return ic


def split():
    ic = Icon("split")
    ic.box(0, 0, 0, 5, 11, 8, BODY)
    plane = ic.proj([(6, -2, -1), (6, 13, -1), (6, 13, 10), (6, -2, 10)])
    ic.shape(plane, BLUE_FILL, ' fill-opacity=".85"')
    ic.outline(plane, BLUE)
    ic.box(7, 0, 0, 12, 11, 8, BODY)
    return ic


def delete_badge(ic, cx, cy, r=5.2, k=2.1):
    """Delete's mark: a dark disc and its white cross, ringed white so it reads on what it takes."""
    ic.raw(
        f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" fill="{DARK}" stroke="#fff" stroke-width="1.4"/>',
        [(cx - r, cy - r), (cx + r, cy + r)],
    )
    ic.raw(
        f'<path d="M{num(cx - k)} {num(cy - k)} L{num(cx + k)} {num(cy + k)} M{num(cx + k)} {num(cy - k)} '
        f'L{num(cx - k)} {num(cy + k)}" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>'
    )


def delete():
    ic = Icon("delete")
    ic.box(0, 0, 0, 11, 11, 8, BODY)
    delete_badge(ic, 7.5, 7)
    return ic


def body():
    """A body with no history, as an imported STEP is: the body's grey, no feature on it."""
    ic = Icon("body")
    ic.box(0, 0, 0, 12, 12, 9, BODY)
    return ic


def offset_face():
    """NX's Offset Region: a body with no history (grey), its top face offset up (the feature's
    amber) and the way it moves."""
    ic = Icon("offset-face")
    ic.box(0, 0, 0, 11, 11, 6, BODY)
    ic.box(0, 0, 6, 11, 11, 9, FEAT)
    start = ic.P(5.5, 5.5, 9)
    ic.arrow(start, (start[0], start[1] - 8))
    return ic


def delete_face():
    """Delete Face: a body with no history, one face picked (amber) and Delete's mark on it."""
    ic = Icon("delete-face")
    ic.box(0, 0, 0, 11, 11, 8, BODY)
    ic.face([(11, 0, 8), (11, 11, 8), (11, 11, 0), (11, 0, 0)], FEAT["right"])
    ic.outline(ic.proj([(11, 0, 8), (11, 11, 8), (11, 11, 0), (11, 0, 0)]), FEAT["edge"])
    delete_badge(ic, 7.5, 7)
    return ic


def ask():
    ic = Icon("ask")
    bubble = (
        "M-7.5 -10 H7.5 A4.5 4.5 0 0 1 12 -5.5 V1 A4.5 4.5 0 0 1 7.5 5.5 H-1.5 L-6.5 10.5 V5.5 H-7.5 "
        "A4.5 4.5 0 0 1 -12 1 V-5.5 A4.5 4.5 0 0 1 -7.5 -10 Z"
    )
    ic.raw(f'<path d="{bubble}" fill="{PURPLE_FILL}"/>', [(-12, -10), (12, 10.5)])
    ic.raw(f'<path d="{bubble}" {edge(PURPLE)}/>')
    star = "M0 -8 C.7 -4.6 1.9 -3.4 5.4 -2.7 C1.9 -2 .7 -.8 0 2.6 C-.7 -.8 -1.9 -2 -5.4 -2.7 C-1.9 -3.4 -.7 -4.6 0 -8 Z"
    ic.raw(f'<path d="{star}" fill="{PURPLE}"/>')
    return ic


# The sketch tools, one each, flat: what each draws, or what it does to what is drawn, with a handle
# at each click it takes. What a tool takes away, or what was there before, is a ghost: dashed and
# faint, and never filled (a half-clear fill greys on a dark page).


def sketch_tool(name):
    """A sketch tool's icon: every one of them is "sketch-" and its name."""
    return Icon(f"sketch-{name}")


def sketch_line():
    ic = sketch_tool("line")
    ic.stroke([(-9.5, 8.5), (9.5, -8.5)], width=CURVE)
    ic.handle(-9.5, 8.5)
    ic.handle(9.5, -8.5)
    return ic


RECTANGLE = [(-10.5, -7.5), (10.5, -7.5), (10.5, 7.5), (-10.5, 7.5)]


def sketch_rectangle():
    ic = sketch_tool("rectangle")
    ic.region(RECTANGLE)
    ic.handle(-10.5, 7.5)
    ic.handle(10.5, -7.5)
    return ic


def sketch_center_rectangle():
    ic = sketch_tool("center-rectangle")
    ic.region(RECTANGLE)
    ic.stroke([(0, 0), (10.5, -7.5)], width=REFERENCE, dash=DASH)
    ic.handle(0, 0)
    ic.handle(10.5, -7.5)
    return ic


def sketch_three_point_rectangle():
    ic = sketch_tool("three-point-rectangle")
    a, b, c, d = (-9, 0.5), (3, -8.5), (9, -0.5), (-3, 8.5)
    ic.region([a, b, c, d])
    for x, y in (a, b, c):
        ic.handle(x, y)
    return ic


def sketch_circle():
    ic = sketch_tool("circle")
    ic.circle(0, 0, 9.5)
    edge_at = polar(0, 0, 9.5, 45)
    ic.stroke([(0, 0), edge_at], width=REFERENCE, dash=DASH)
    ic.handle(0, 0)
    ic.handle(*edge_at)
    return ic


def sketch_three_point_circle():
    ic = sketch_tool("three-point-circle")
    ic.circle(0, 0, 9.5)
    for degrees in (150, 30, 270):
        ic.handle(*polar(0, 0, 9.5, degrees))
    return ic


def sketch_arc():
    ic = sketch_tool("arc")
    centre = (0, 6)
    start, end = ic.arc(*centre, 11.5, 25, 155)
    for at in (start, end):
        ic.stroke([centre, at], width=REFERENCE, dash=DASH)
    for at in (centre, start, end):
        ic.handle(*at)
    return ic


def sketch_three_point_arc():
    ic = sketch_tool("three-point-arc")
    start, end, top = (-10, 5), (10, 5), (0, -6)
    # its centre (0, c), as far from an end as from the top: 10**2 + (5 - c)**2 = (c + 6)**2
    c = (10 ** 2 + 5 ** 2 - 6 ** 2) / (2 * 5 + 2 * 6)
    spread = math.degrees(math.atan2(c - end[1], end[0]))
    ic.arc(0, c, c - top[1], spread, 180 - spread)
    for at in (start, top, end):
        ic.handle(*at)
    return ic


def sketch_tangent_arc():
    ic = sketch_tool("tangent-arc")
    ic.stroke([(-11, 7), (-2, 7)], width=CURVE)
    _, end = ic.arc(-2, -3, 10, 270, 360)
    ic.handle(-2, 7)
    ic.handle(*end)
    return ic


def slot_path(half=6, r=5.5):
    return (f"M{num(-half)} {num(-r)} H{num(half)} A{num(r)} {num(r)} 0 0 1 {num(half)} {num(r)} H{num(-half)} "
            f"A{num(r)} {num(r)} 0 0 1 {num(-half)} {num(-r)} Z"), [(-half - r, -r), (half + r, r)]


def sketch_slot():
    ic = sketch_tool("slot")
    d, extent = slot_path()
    ic.curve(d, extent, fill=BLUE_FILL)
    ic.handle(-6, 0)
    ic.handle(6, 0)
    return ic


def sketch_center_slot():
    ic = sketch_tool("center-slot")
    d, extent = slot_path()
    ic.curve(d, extent, fill=BLUE_FILL)
    ic.stroke([(-6, 0), (6, 0)], width=REFERENCE, dash=DASH)
    ic.handle(0, 0)
    ic.handle(6, 0)
    return ic


def sketch_polygon():
    ic = sketch_tool("polygon")
    ic.region([polar(0, 0, 10.5, 60 * i) for i in range(6)])
    ic.stroke([(0, 0), (10.5, 0)], width=REFERENCE, dash=DASH)
    ic.handle(0, 0)
    ic.handle(10.5, 0)
    return ic


def sketch_spline():
    ic = sketch_tool("spline")
    ic.curve("M-10.5 6 C-8 -5 -3 -6 0 0 S8 6 10.5 -6", [(-10.5, -4), (10.5, 4), (-10.5, 6), (10.5, -6)])
    for x, y in ((-10.5, 6), (0, 0), (10.5, -6)):
        ic.handle(x, y)
    return ic


def sketch_reference_line():
    ic = sketch_tool("reference-line")
    ic.stroke([(-9.5, 8.5), (9.5, -8.5)], width=1.6, dash="3 1.8")
    ic.handle(-9.5, 8.5)
    ic.handle(9.5, -8.5)
    return ic


def sketch_point():
    ic = sketch_tool("point")
    for degrees in (0, 90, 180, 270):
        ic.stroke([polar(0, 0, 4.8, degrees), polar(0, 0, 9.5, degrees)], width=1.6)
    ic.handle(0, 0, 2.6)
    return ic


def dimension(ic, y, x0, x1, foot):
    """A dimension between x0 and x1 at height y, its extension lines down to `foot`."""
    for x in (x0, x1):
        ic.stroke([(x, foot), (x, y - 2.2)], width=1)
    middle = ((x0 + x1) / 2, y)
    ic.arrow(middle, (x0, y), width=1.3, length=3.4, half=2)
    ic.arrow(middle, (x1, y), width=1.3, length=3.4, half=2)


def sketch_dimension():
    ic = sketch_tool("dimension")
    ic.stroke([(-9.5, 8.5), (9.5, 8.5)], width=CURVE)
    dimension(ic, -2, -9.5, 9.5, 6)
    value = [(-4, -8.5), (4, -8.5), (4, -4.5), (-4, -4.5)]
    ic.shape(value, "#fff")
    ic.outline(value, BLUE)
    for at in ((-9.5, 8.5), (9.5, 8.5)):
        ic.handle(*at)
    return ic


def corner(kind):
    """A corner made round (Fillet) or cut (Chamfer), clicked at the sharp corner it was, a ghost."""
    ic = sketch_tool(kind)
    ic.curve("M-9 0 V-9 H0", [(-9, -9), (0, 0)], dash=DASH, opacity=GHOSTLY)
    turn = "A9 9 0 0 1 0 -9" if kind == "fillet" else "L0 -9"
    ic.curve(f"M-9 10.5 V0 {turn} H10.5", [(-9, -9), (10.5, 10.5)], width=2.2)
    ic.handle(-9, -9)
    return ic


def sketch_trim():
    ic = sketch_tool("trim")
    ic.stroke([(3, -10), (3, 10)], width=CURVE)
    ic.stroke([(-10.5, 1), (3, 1)], width=CURVE)
    ic.curve("M3 1 H10.5", [(3, 1), (10.5, 1)], dash=DASH, opacity=GHOSTLY)
    # the click on the piece cut away
    ic.stroke([(5, -1.5), (9.5, 3.5)], width=1.6)
    ic.stroke([(9.5, -1.5), (5, 3.5)], width=1.6)
    return ic


def sketch_extend():
    ic = sketch_tool("extend")
    ic.stroke([(8, -10), (8, 10)], width=CURVE)
    ic.stroke([(-10.5, 1), (-2, 1)], width=CURVE)
    ic.curve("M-2 1 H4", [(-2, 1), (4, 1)], dash=DASH)
    ic.head((8, 1), (0, 1), length=3.6, half=2.2)
    ic.handle(-2, 1)
    return ic


def sketch_offset():
    ic = sketch_tool("offset")
    # a chain, and the same chain 5 in from it
    ic.curve("M-10 10.5 V-1 A9 9 0 0 1 -1 -10 H10.5", [(-10, -10), (10.5, 10.5)], dash=DASH, opacity=GHOSTLY)
    ic.curve("M-5 10.5 V-1 A4 4 0 0 1 -1 -5 H10.5", [(-5, -5), (10.5, 10.5)])
    ic.arrow((7, -10), (7, -5.6), width=1.2, length=2.8, half=1.7)
    return ic


def sketch_mirror():
    ic = sketch_tool("mirror")
    ic.stroke([(0, -11), (0, 11)], width=REFERENCE, dash=DASH)
    ic.region([(-2.5, -8), (-2.5, 8), (-10.5, 8)])
    ic.region([(2.5, -8), (2.5, 8), (10.5, 8)], ghost=True)
    return ic


def sketch_move():
    ic = sketch_tool("move")
    ic.circle(-5.5, 4.5, 5, ghost=True)
    ic.circle(5.5, -4.5, 5)
    ic.arrow((-5.5, 4.5), (2.3, -1.9), width=1.4, length=3.4, half=2)
    ic.handle(5.5, -4.5)
    return ic


def sketch_copy():
    ic = sketch_tool("copy")
    ic.circle(-5.5, 4.5, 5)
    ic.circle(5.5, -4.5, 5)
    ic.arrow((-5.5, 4.5), (2.3, -1.9), width=1.4, length=3.4, half=2)
    ic.handle(-5.5, 4.5)
    ic.handle(5.5, -4.5)
    return ic


def sketch_rotate():
    ic = sketch_tool("rotate")
    pivot, turn = (-6, 8), math.radians(50)

    def turned(x, y):
        return (pivot[0] + x * math.cos(turn) + y * math.sin(turn), pivot[1] - x * math.sin(turn) + y * math.cos(turn))

    bar = [(0, 0), (15, 0), (15, -6), (0, -6)]
    ic.region([(pivot[0] + x, pivot[1] + y) for x, y in bar], ghost=True)
    ic.region([turned(x, y) for x, y in bar])
    ic.arc(*pivot, 17, 8, 36, width=1.4)
    ic.head(polar(*pivot, 17, 44), polar(*pivot, 17, 36), length=3.6, half=2.1)
    ic.handle(*pivot)
    return ic


def sketch_scale():
    ic = sketch_tool("scale")
    ic.region([(-10, 9), (-10, -10), (9, -10), (9, 9)])
    ic.region([(-10, 9), (-10, 1), (-2, 1), (-2, 9)], ghost=True)
    ic.arrow((-3, 0), (5.5, -6.5), width=1.4, length=3.4, half=2)
    ic.handle(-10, 9)
    return ic


def sketch_linear_pattern():
    ic = sketch_tool("linear-pattern")
    ic.circle(-8, 4, 3.6)
    for x in (0, 8):
        ic.circle(x, 4, 3.6, ghost=True)
    ic.arrow((-8, -5.5), (11.5, -5.5), width=1.4, length=3.4, half=2)
    return ic


def sketch_circular_pattern():
    ic = sketch_tool("circular-pattern")
    ic.circle(0, 0, 8, width=REFERENCE, dash=DASH, fill="none")
    ic.circle(*polar(0, 0, 8, 90), 3.4)
    for degrees in (210, 330):
        ic.circle(*polar(0, 0, 8, degrees), 3.4, ghost=True)
    ic.handle(0, 0)
    return ic


def sketch_project():
    """Project Curve: a face of the part, and its edges brought down into the sketch."""
    ic = sketch_tool("project")
    plane = ic.proj([(-1, -1, 0), (11, -1, 0), (11, 11, 0), (-1, 11, 0)])
    ic.shape(plane, BLUE_FILL)
    ic.outline(plane, BLUE)
    foot = ic.proj([(1, 1, 0), (9, 1, 0), (9, 9, 0), (1, 9, 0)])
    ic.raw(f'<path d="{ic.d(foot)}" fill="none" stroke="{BLUE}" stroke-width="{num(CURVE)}" stroke-linejoin="round"/>', foot)
    for x, y in ((9, 1), (9, 9), (1, 9)):
        ic.stroke([ic.P(x, y, 0), ic.P(x, y, 6)], width=1, dash="1.6 1.4")
    ic.box(1, 1, 6, 9, 9, 11, BODY)
    return ic


def sketch_intersection():
    """Intersection Curve: where the part crosses the sketch's plane, drawn on the part."""
    ic = sketch_tool("intersection")
    ic.box(1, 1, 0, 9, 9, 4.5, BODY)
    plane = ic.proj([(-1, -1, 4.5), (11, -1, 4.5), (11, 11, 4.5), (-1, 11, 4.5)])
    ic.shape(plane, BLUE_FILL, ' fill-opacity=".85"')
    ic.outline(plane, BLUE)
    ic.box(1, 1, 4.5, 9, 9, 10, BODY)
    loop = ic.proj([(9, 1, 4.5), (9, 9, 4.5), (1, 9, 4.5)])
    ic.raw(f'<path d="{ic.d(loop, False)}" fill="none" stroke="{BLUE}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>', loop)
    return ic


def sketch_convert_reference():
    """Convert To/From Reference: a curve made a reference line, or back."""
    ic = sketch_tool("convert-reference")
    ic.stroke([(-11, 4), (1, -8)], width=CURVE)
    ic.stroke([(-1, 8), (11, -4)], width=1.6, dash="3 1.8")
    # one into the other, and back
    ic.arrow((0.5, 0.5), (-3.2, -3.2), width=1.3, length=3, half=1.8)
    ic.arrow((-0.5, -0.5), (3.2, 3.2), width=1.3, length=3, half=1.8)
    return ic


def finish_sketch():
    ic = Icon("finish-sketch")
    plane = ic.proj([(0, 0, 0), (12, 0, 0), (12, 12, 0), (0, 12, 0)])
    ic.shape(plane, BLUE_FILL)
    ic.outline(plane, BLUE)
    arc = [(6 + 3 * math.cos(math.radians(a)), 6 + 3 * math.sin(math.radians(a)), 0) for a in range(0, 181, 15)]
    ic.stroke(ic.proj([(3, 3, 0), (9, 3, 0)] + arc + [(3, 3, 0)]), width=1.6)
    tick = [(2.5, -4.5), (6, -1), (12.5, -9)]
    ic.stroke(tick, "#fff", width=4.6)
    ic.stroke(tick, BLUE, width=2.6)
    return ic


# The workspace's other tools: what each looks at or does, on the part.


def silhouette(ic, x0, y0, z0, x1, y1, z1):
    P = ic.P
    return [P(x0, y0, z1), P(x1, y0, z1), P(x1, y0, z0), P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1)]


SELECT_KINDS = ("all", "face", "edge", "face-group", "edge-group", "body", "part", "position")


def select(kind):
    """Select, and each of its filters: the pointer on a block, what it picks in the pick's orange."""
    ic = Icon("select" if kind == "all" else f"select-{kind}")
    s, h = 10, 6
    if kind == "part":
        # an assembly's part: the block on the plate, picked alone
        ic.box(-1.5, -1.5, 0, s + 1.5, s + 1.5, 2.5, BODY)
        ic.box(1.5, 1.5, 2.5, s - 1.5, s - 1.5, h + 2.5, FEAT)
        ic.pointer((2.5, 0.5))
        return ic
    if kind == "position":
        # a joint's knob, taken to turn the part on it
        ic.box(0, 0, 0, s, s, 4, BODY)
        cx, cy = ic.P(s / 2, s / 2, 9)
        ic.raw(f'<path d="M{num(cx - 9)} {num(cy)} A9 4.5 0 0 0 {num(cx + 7.8)} {num(cy + 2.25)}" fill="none" stroke="{BLUE}" '
               f'stroke-width="1.5" stroke-linecap="round"/>', [(cx - 9, cy), (cx, cy + 4.5)])
        ic.head((cx + 9.6, cy - 0.6), (cx + 7.8, cy + 2.25), length=3.6, half=2.2)
        knob = (cx - 3.5, cy + 4.15)
        ic.raw(f'<circle cx="{num(knob[0])}" cy="{num(knob[1])}" r="2.6" fill="#fff"/>', [(knob[0] - 2.6, knob[1] - 2.6)])
        ic.raw(f'<circle cx="{num(knob[0])}" cy="{num(knob[1])}" r="2.6" {edge(BLUE)}/>')
        ic.pointer((knob[0] + 0.5, knob[1] + 0.5))
        return ic
    ic.box(0, 0, 0, s, s, h, FEAT if kind == "body" else BODY)
    if kind == "face":
        top = ic.proj([(0, 0, h), (s, 0, h), (s, s, h), (0, s, h)])
        ic.shape(top, FEAT["top"])
        ic.outline(top, FEAT["edge"])
    elif kind == "face-group":
        for pts, tone in (([(0, 0, h), (s, 0, h), (s, s, h), (0, s, h)], FEAT["top"]),
                          ([(0, s, h), (s, s, h), (s, s, 0), (0, s, 0)], FEAT["left"])):
            ic.face(pts, tone)
            ic.outline(ic.proj(pts), FEAT["edge"])
    elif kind == "edge":
        ic.stroke([ic.P(s, 0, h), ic.P(s, s, h)], FEAT["right"], width=2.6)
    elif kind == "edge-group":
        # the chain of edges round its top face
        ic.stroke(ic.proj([(0, 0, h), (s, 0, h), (s, s, h), (0, s, h), (0, 0, h)]), FEAT["right"], width=2.4)
    tips = {"all": (3.5, 4.5), "face": (1, -1.5), "edge": (4, 2), "face-group": (-4, 3.5), "edge-group": (4, 2), "body": (3.5, 4.5)}
    ic.pointer(tips[kind])
    return ic


MEASURE_KINDS = ("all", "vertex", "edge", "face")


def measure(kind):
    """Measure, and each of its filters: a distance over a block, what it measures alone in the pick's orange."""
    ic = Icon("measure" if kind == "all" else f"measure-{kind}")
    s, h = 12, 6
    ic.box(0, 0, 0, s, s, h, BODY)
    if kind == "face":
        top = ic.proj([(0, 0, h), (s, 0, h), (s, s, h), (0, s, h)])
        ic.shape(top, FEAT["top"])
        ic.outline(top, FEAT["edge"])
    elif kind == "edge":
        ic.stroke([ic.P(0, s, h), ic.P(s, s, h)], FEAT["right"], width=2.6)
    # the distance between two of its corners, measured over it
    dimension(ic, -9.5, -12, 12, -1.5)
    for x in (-12, 12):
        if kind == "vertex":
            dot = [(x - 2, -2), (x + 2, -2), (x + 2, 2), (x - 2, 2)]
            ic.shape(dot, FEAT["top"])
            ic.outline(dot, FEAT["edge"])
        elif kind == "all":
            ic.handle(x, 0, 1.6)
    return ic


def measure_bodies():
    """Measure Bodies: a body, and where its mass centres."""
    ic = Icon("measure-bodies")
    ic.box(0, 0, 0, 12, 12, 8, BODY)
    cx, cy, r = 0, 1.5, 5
    ic.raw(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" fill="#fff"/>', [(cx - r, cy - r), (cx + r, cy + r)])
    ic.raw(f'<path d="M{num(cx)} {num(cy)} V{num(cy - r)} A{num(r)} {num(r)} 0 0 1 {num(cx + r)} {num(cy)} Z '
           f'M{num(cx)} {num(cy)} V{num(cy + r)} A{num(r)} {num(r)} 0 0 1 {num(cx - r)} {num(cy)} Z" fill="{DARK}"/>')
    ic.raw(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" {edge(DARK)}/>')
    return ic


def draft_analysis():
    """Draft Analysis: a drafted body, its faces shaded by how they draw against the pull above it."""
    ic = Icon("draft-analysis")
    b, a, h = 12, 2.6, 8
    P = ic.P
    sil = [P(a, a, h), P(b - a, a, h), P(b, 0, 0), P(b, b, 0), P(0, b, 0), P(a, b - a, h)]
    ic.shape(sil, BODY["right"])
    ic.face([(a, a, h), (b - a, a, h), (b - a, b - a, h), (a, b - a, h)], BODY["top"])
    ic.face([(a, b - a, h), (b - a, b - a, h), (b, b, 0), (0, b, 0)], DRAWS["left"])
    ic.face([(b - a, a, h), (b - a, b - a, h), (b, b, 0), (b, 0, 0)], DRAWS["right"])
    ic.outline(sil, BODY["edge"])
    top = P(b / 2, b / 2, h)
    ic.arrow(top, (top[0], top[1] - 11.5))
    return ic


def section():
    """Edit Section: the part cut on a plane, the half before it gone, what the cut shows hatched."""
    ic = Icon("section")
    s, h, cut = 12, 8, 6
    ic.outline(silhouette(ic, cut, 0, 0, s, s, h), BODY["edge"], dash="1.6 1.4")
    ic.box(0, 0, 0, cut, s, h, BODY)
    face = ic.proj([(cut, 0, h), (cut, s, h), (cut, s, 0), (cut, 0, 0)])
    ic.shape(face, BLUE_FILL)
    ic.raw(f'<g clip-path="url(#{ic.clip(face)})">')
    for k in range(-2, 5):
        a, b = ic.P(cut, 3 * k, h + 2), ic.P(cut, 3 * k + 10, h - 8)
        ic.raw(f'<path d="M{num(a[0])} {num(a[1])} L{num(b[0])} {num(b[1])}" stroke="{BLUE}" stroke-width=".9"/>')
    ic.raw("</g>")
    ic.outline(face, BLUE)
    plane = ic.proj([(cut, -2, -1.5), (cut, s + 2, -1.5), (cut, s + 2, h + 1.5), (cut, -2, h + 1.5)])
    ic.outline(plane, BLUE)
    return ic


def exploded():
    """Exploded Views: an assembly's parts drawn apart, along the way they come off."""
    ic = Icon("exploded")
    ic.box(0, 0, 0, 11, 11, 4, BODY)
    lo, hi, z0 = 2.5, 8.5, 8.5
    for x, y in ((hi, lo), (hi, hi), (lo, hi)):
        ic.stroke([ic.P(x, y, 4), ic.P(x, y, z0)], width=1, dash="1.6 1.4")
    ic.box(lo, lo, z0, hi, hi, z0 + 4, BODY)
    return ic


def interference():
    """Simple Interference: two bodies, and the volume both fill, seen through the one in front."""
    ic = Icon("interference")
    ic.box(0, 0, 0, 8, 8, 9.5, BODY)
    ic.box(3.5, 3.5, 0, 13, 13, 5, BODY)
    ic.box(3.5, 3.5, 0, 8, 8, 5, FEAT)
    ic.box(0, 0, 5, 8, 8, 9.5, BODY)
    return ic


def compare():
    """Compare: the part as it is, what it gained in the feature's color, what it lost a ghost."""
    ic = Icon("compare")
    ic.box(0, 0, 0, 12, 12, 5, BODY)
    ic.outline(silhouette(ic, 7, 0.5, 5, 11.5, 5, 10), BODY["edge"], dash="1.6 1.4")
    ic.box(0.5, 6, 5, 5.5, 11.5, 10, FEAT)
    return ic


def appearance():
    """Edit Object Display: the part's color, picked: a ball shaded as the part is."""
    ic = Icon("appearance")
    r = 10.5
    fill = ic.gradient((-5, -6), (6, 8), [(0, "#FFFFFF"), (0.35, BODY["left"]), (1, BODY["right"])])
    ic.raw(f'<circle cx="0" cy="0" r="{num(r)}" fill="{fill}"/>', [(-r, -r), (r, r)])
    ic.raw(f'<circle cx="0" cy="0" r="{num(r)}" {edge(BODY["edge"])}/>')
    # a drop of the color it is given, on it
    drop = "M5.5 -1 C5.5 -1 1.5 3.6 1.5 6.2 A4 4 0 0 0 9.5 6.2 C9.5 3.6 5.5 -1 5.5 -1 Z"
    ic.raw(f'<path d="{drop}" fill="{BLUE}"/>', [(1.5, -1), (9.5, 10.2)])
    ic.raw(f'<path d="{drop}" fill="none" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/>')
    return ic


def orient_view():
    """Orient View: the plane picked, turned from where it is seen to square on to the view."""
    ic = Icon("orient-view")
    seen = [(-12.5, 6.5), (-4.5, 2.5), (3.5, 6.5), (-4.5, 10.5)]
    ic.shape(seen, BLUE_FILL)
    ic.outline(seen, BLUE, dash="1.6 1.4")
    square = [(-0.5, -11.5), (12.5, -11.5), (12.5, 1.5), (-0.5, 1.5)]
    ic.shape(square, BLUE_FILL)
    ic.outline(square, BLUE)
    # its normal, pointing out at the one looking
    cx, cy, r = 6, -5, 3.2
    ic.raw(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" fill="#fff"/>')
    ic.raw(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" {edge(BLUE)}/>')
    ic.raw(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="1.3" fill="{BLUE}"/>')
    ic.raw(f'<path d="M-9.5 3.5 C-9.5 -2.5 -7.5 -5 -4.6 -5" fill="none" stroke="{BLUE}" stroke-width="1.6" stroke-linecap="round"/>',
           [(-9.5, -5)])
    ic.head((-0.9, -5), (-5, -5), length=4, half=2.3)
    return ic


PAPER = [(-12, -9), (12, -9), (12, 9), (-12, 9)]


def drawing_sheet(ic):
    """A drawing's sheet and its title block."""
    ic.shape(PAPER, "#fff")
    ic.outline(PAPER, BODY["edge"])
    block = [(3, 4), (12, 4), (12, 9), (3, 9)]
    ic.shape(block, BODY["top"])
    ic.outline(block, BODY["edge"])
    ic.stroke([(3, 6.5), (12, 6.5)], BODY["edge"], width=0.8)


def drawing():
    ic = Icon("drawing")
    drawing_sheet(ic)
    ic.box(-4.5, 1, 0, 1.5, 7, 4.5, BODY)  # the part's view, at the sheet's top left
    return ic


def turn(name, back):
    """Undo (`back`) and Redo: the change last made, turned back, or made again."""
    ic = Icon(name)
    cx, cy, r = 0, 2.5, 8.5
    # up over the top from below on one side, and down on the other, where the head points
    a0, a1 = (-35, 188) if back else (215, -8)
    steps = [a0 + (a1 - a0) * i / 24 for i in range(25)]
    arc = [polar(cx, cy, r, a) for a in steps]
    ic.stroke(arc[:-4], width=2.4)
    ic.head(arc[-1], arc[-4], length=5.2, half=3.4)
    return ic


def assembly_constraints():
    """Assembly Constraints: a part brought to another, its pin on the hole's axis."""
    ic = Icon("assembly-constraints")
    ic.box(0, 0, 0, 12, 12, 5, BODY)
    ic.hole(6, 6, 5, 3.6, 2.4, wall=BODY["right"], rim=BODY["edge"])
    x, top = ic.P(6, 6, 5)
    ic.stroke([(x, top), (x, top - 15)], width=1.2, dash=DASH)
    ic.cylinder(6, 6, 10, 15.5, 3.6, BODY, side=f"url(#{BSIDE})")
    ic.arrow((x + 6.5, top - 13), (x + 6.5, top - 3.5), width=1.4, length=3.4, half=2)
    return ic


def part():
    """A part: one body, a bracket."""
    ic = Icon("part")
    s, t, H = 12, 2.5, 10
    P = ic.P
    sil = [P(0, 0, H), P(t, 0, H), P(t, 0, t), P(s, 0, t), P(s, 0, 0), P(s, s, 0), P(0, s, 0), P(0, s, H)]
    ic.shape(sil, BODY["right"])
    ic.face([(0, 0, H), (t, 0, H), (t, s, H), (0, s, H)], BODY["top"])
    ic.face([(t, 0, t), (s, 0, t), (s, s, t), (t, s, t)], BODY["top"])
    ic.face([(t, 0, H), (t, s, H), (t, s, t), (t, 0, t)], BODY["right"])
    ic.face([(s, 0, t), (s, s, t), (s, s, 0), (s, 0, 0)], BODY["right"])
    ic.face([(0, s, 0), (s, s, 0), (s, s, t), (t, s, t), (t, s, H), (0, s, H)], BODY["left"])
    ic.outline(sil, BODY["edge"])
    ic.hole(7.5, 6, t, 2.4, 1.6, wall=BODY["right"], rim=BODY["edge"])
    return ic


def assembly():
    """An assembly: parts placed together, a block and a pin on a plate."""
    ic = Icon("assembly")
    ic.box(0, 0, 0, 13, 13, 2.5, BODY)
    ic.box(1, 1, 2.5, 6.5, 12, 8, BODY)
    ic.cylinder(9.8, 7, 2.5, 8.5, 2.6, BODY, side=f"url(#{BSIDE})")
    return ic


def move():
    """Move Object: the body where it was, a ghost, and where it is now."""
    ic = Icon("move")
    s, h, d = 7, 6, 8
    for pts, tone in (([(0, 0, h), (s, 0, h), (s, s, h), (0, s, h)], GHOST["top"]),
                      ([(0, s, h), (s, s, h), (s, s, 0), (0, s, 0)], GHOST["left"]),
                      ([(s, 0, h), (s, s, h), (s, s, 0), (s, 0, 0)], GHOST["right"])):
        ic.face(pts, tone)
    ic.outline(silhouette(ic, 0, 0, 0, s, s, h), GHOST["edge"], dash="1.6 1.4")
    ic.box(d, 0, 0, d + s, s, h, FEAT)
    ic.arrow(ic.P(1, s / 2, h + 3), ic.P(d + s - 1, s / 2, h + 3))
    return ic


def expressions():
    """Expressions: a part's named values, a name equal to its value."""
    ic = Icon("expressions")
    card = [(-11.5, -8), (11.5, -8), (11.5, 8), (-11.5, 8)]
    ic.shape(card, "#fff")
    ic.outline(card, BODY["edge"])
    # a name, equal to its value
    ic.stroke([(-8, -3), (-3, 3)], DARK, width=1.5)
    ic.stroke([(-3, -3), (-8, 3)], DARK, width=1.5)
    for y in (-1.6, 1.6):
        ic.stroke([(-0.5, y), (3.5, y)], BLUE, width=1.5)
    value = [(5.5, -3), (9, -3), (9, 3), (5.5, 3)]
    ic.shape(value, BLUE_FILL)
    ic.outline(value, BLUE)
    return ic


# The agent's tools, in its purple.


def smooth(points):
    """A hand-drawn mark through `points`: each bend rounded off, as a pen draws it."""
    (x0, y0), (xn, yn) = points[0], points[-1]
    bends = [f"Q{num(x)} {num(y)} {num((x + nx) / 2)} {num((y + ny) / 2)}" for (x, y), (nx, ny) in zip(points[1:-1], points[2:])]
    return " ".join([f"M{num(x0)} {num(y0)}", *bends, f"L{num(xn)} {num(yn)}"])


def add_context():
    """Add to context: the selection put into the chat box, to go with the next message."""
    ic = Icon("add-context")
    bubble = (
        "M-7.5 -10 H7.5 A4.5 4.5 0 0 1 12 -5.5 V1 A4.5 4.5 0 0 1 7.5 5.5 H-1.5 L-6.5 10.5 V5.5 H-7.5 "
        "A4.5 4.5 0 0 1 -12 1 V-5.5 A4.5 4.5 0 0 1 -7.5 -10 Z"
    )
    ic.raw(f'<path d="{bubble}" fill="{PURPLE_FILL}"/>', [(-12, -10), (12, 10.5)])
    ic.raw(f'<path d="{bubble}" {edge(PURPLE)}/>')
    ic.stroke([(-4.8, -2.25), (4.8, -2.25)], PURPLE, width=2.4)
    ic.stroke([(0, -7), (0, 2.5)], PURPLE, width=2.4)
    return ic


def annotate():
    """Annotate: a mark drawn on the part, with the agent's marker."""
    ic = Icon("annotate")
    drawn_on(ic)
    mark = ic.proj([(1.5, 10.5, 5), (3.5, 7, 5), (6, 8.5, 5), (8, 4.5, 5), (10.5, 5.5, 5)])
    ic.raw(f'<path d="{smooth(mark)}" fill="none" stroke="{PURPLE}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>', mark)
    ic.marker(mark[-1])
    return ic


def drawn_on(ic):
    """The part the agent's marks are drawn on: a block, its top face the page."""
    ic.box(0, 0, 0, 12, 12, 5, BODY)


def highlighter():
    """Annotate's highlighter: a broad, clear band over the part, with its chisel."""
    ic = Icon("annotate-highlighter")
    drawn_on(ic)
    a, b = ic.P(1.5, 9, 5), ic.P(9.5, 2.5, 5)
    ic.raw(f'<path d="M{num(a[0])} {num(a[1])} L{num(b[0])} {num(b[1])}" fill="none" stroke="{PURPLE}" stroke-width="4.4" '
           f'stroke-opacity=".45" stroke-linecap="butt"/>', [a, b])
    ic.marker(b, chisel=True)
    return ic


def eraser():
    """Annotate's eraser: a mark taken off the part where it has been."""
    ic = Icon("annotate-eraser")
    drawn_on(ic)
    mark = ic.proj([(1.5, 10.5, 5), (3.5, 7, 5), (6, 8.5, 5), (8, 4.5, 5), (10.5, 5.5, 5)])
    kept, gone = smooth(mark[:3]), smooth(mark[2:])
    ic.raw(f'<path d="{kept}" fill="none" stroke="{PURPLE}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>', mark)
    ic.raw(f'<path d="{gone}" fill="none" stroke="{PURPLE}" stroke-width="1.8" stroke-linecap="round" stroke-dasharray="{DASH}" opacity="{num(GHOSTLY)}"/>')
    ic.rubber(mark[-1])
    return ic


SHAPE_KINDS = ("rectangle", "line", "arrow", "ellipse", "text")


def shape_mark(kind):
    """Each of Shapes' tools, as its mark on the part."""
    ic = Icon(f"shapes-{kind}")
    drawn_on(ic)
    stroke = f'fill="none" stroke="{PURPLE}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "rectangle":
        box = ic.proj([(2, 3, 5), (10, 3, 5), (10, 10, 5), (2, 10, 5)])
        ic.raw(f'<path d="{ic.d(box)}" fill="{PURPLE_FILL}" stroke="{PURPLE}" stroke-width="1.9" stroke-linejoin="round"/>', box)
    elif kind == "line":
        a, b = ic.P(1.5, 9.5, 5), ic.P(10.5, 2.5, 5)
        ic.raw(f'<path d="M{num(a[0])} {num(a[1])} L{num(b[0])} {num(b[1])}" {stroke}/>', [a, b])
    elif kind == "arrow":
        ic.arrow((11, -10.5), (1.5, 0.5), PURPLE, width=1.9, length=4.8, half=2.8)
    elif kind == "ellipse":
        cx, cy = ic.P(6, 6, 5)
        ic.raw(f'<ellipse cx="{num(cx)}" cy="{num(cy)}" rx="7.4" ry="3.7" fill="{PURPLE_FILL}" stroke="{PURPLE}" stroke-width="1.9"/>',
               [(cx - 7.4, cy - 3.7), (cx + 7.4, cy + 3.7)])
    else:
        # a T, as text is set over the part
        ic.raw(f'<path d="M-5 -9 H5 M0 -9 V3" fill="none" stroke="{PURPLE}" stroke-width="2.6" stroke-linecap="round"/>', [(-5, -9), (5, 3)])
    return ic


def shapes():
    """Shapes: a box drawn on the part and an arrow at it, in the agent's purple."""
    ic = Icon("shapes")
    drawn_on(ic)
    box = ic.proj([(2, 4, 5), (9, 4, 5), (9, 11, 5), (2, 11, 5)])
    ic.raw(f'<path d="{ic.d(box)}" fill="{PURPLE_FILL}" stroke="{PURPLE}" stroke-width="1.7" stroke-linejoin="round"/>', box)
    ic.arrow((12.5, -9.5), (5, -1.2), PURPLE, width=1.8, length=4.4, half=2.6)
    return ic


# Every icon, in the sprite's order, by the group the sheet shows it in: the set Amy approved, then
# what the workspace adds to it.
GROUPS = (
    ("Approved", "The modeling commands and the Part Navigator's features, as Amy approved them; the check is a status mark.", (
        sketch, extrude, revolve, hole, lambda: rounded("blend"), lambda: rounded("chamfer"), shell, draft, rib,
        pattern, mirror, datum_plane, csys, sweep, loft, split, delete, body, offset_face, delete_face, ask,
    )),
    ("The agent's tools", "Beside Ask, in the agent's purple: Add to context; Annotate (the Pencil) with its pen, "
     "highlighter and eraser; Shapes, and each shape it draws.", (
        add_context, annotate, highlighter, eraser, shapes, *((lambda kind=kind: shape_mark(kind)) for kind in SHAPE_KINDS),
    )),
    ("The workspace's tools", "The strip's tools, the Analysis, View, Assemblies and Drafting tabs, Expressions, "
     "and Undo and Redo.", (
        lambda: select("all"), lambda: measure("all"), section, exploded, measure_bodies, draft_analysis, interference,
        compare, appearance, orient_view, drawing, assembly_constraints, expressions,
        lambda: turn("undo", back=True), lambda: turn("redo", back=False),
    )),
    ("Select's and Measure's filters", "What each picks alone, the pick in the selection's orange, and how Select grows a pick.", (
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
        ['<svg width="0" height="0" style="position:absolute" aria-hidden="true">', f"<defs>{SHARED}</defs>"]
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
// The CAD workspace's icons, drawn in NX's language: one hidden SVG sprite (NxIconSprite), mounted
// once, and NxIcon, which draws one of its symbols by name. Every id in the sprite starts with "@PREFIX@".

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
 * The icons' symbols and the gradient they share, hidden. Mount it once in the page: every NxIcon
 * draws from it.
 */
export function NxIconSprite() {
  return SPRITE;
}

/**
 * One icon of the sprite, by name. Its symbol's own viewBox fits it to the box `className` gives the
 * svg, so the class sets its size, as with the other icons.
 */
export function NxIcon({ name, className }) {
  return <svg className={className} aria-hidden="true" focusable="false"><use href={`#@PREFIX@${name}`} /></svg>;
}
"""


def module():
    """The viewer's module: the icons' names, the sprite as a component, and NxIcon."""
    drawn = symbols()
    markup = [f"<defs>{SHARED}</defs>"] + [symbol for _, symbol in drawn]
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
.light { background: #ffffff; }
.dark { background: #27292d; }
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
