"""Adaptive clearing, shared by ``adaptive`` (2.5D) and ``adaptive_3d``: one level at a time, the tool's radial
engagement held to the stepover, and the tool kept where material stands.

A level comes as ``area``, where the tool's centre may go at that height (in tool-centre space: the region to clear
shrunk by the radius, or kept a radius off the part), and ``standing``, the material standing across the level: the
stock as it stands before the operation (:meth:`~cadgen._internal.cam.milling3d.StockNow.standing`, every earlier
operation and setup replayed), or the whole stock where that is not simulated. Where the tool's circle touches none of
it the level is already clear (``air``); where it touches some is what the level cuts (``todo``). A level with nothing
to cut is skipped, and so is a connected piece of ``area`` with nothing in it.

How a piece is cleared (in tool-centre space):

* it starts from the air in it: the cleared area is first the positions where the tool touches nothing (beside the
  stock, over what an earlier operation or a shallower level already cut). Where a piece has no air, it is entered by a
  helix at its most open point (the centre of its largest inscribed circle; radius up to ``0.75`` of the tool radius at
  ``ramp_angle_deg``), or, where it is too narrow for that, a ramp along its outline (else a plunge, counted);
* it then grows the cleared area in steps of the stepover: each new boundary is the cleared area offset by the
  stepover and clipped to the piece, so no point of a new pass is more than one stepover from where the tool has
  already been, or from where it would touch nothing: that caps the radial engagement at the stepover, walls
  included. Only the stretches of each boundary that reach new material are cut (climb by default), the nearest one
  first, joined by feeds through cleared space or a lift when the way is not clear. A stretch that starts in the air
  is come down to straight; any other after a lift is ramped into along itself, or come down to straight only where
  the level is already cut all round the tool.

What the radius cannot reach goes to the ``corner_radius`` check as in a pocket; what is cut at full width (round a
piece too narrow for a helix) goes to ``state["full_slot"]``.
"""

from __future__ import annotations

__all__ = ["Clearing"]


class Clearing:
    """One operation's adaptive clearing, level by level, on one builder."""

    def __init__(self, ctx, b, *, stepover: float, feeds, climb: bool, ramp_angle_deg: float):
        self.ctx = ctx
        self.b = b
        self.stepover = stepover
        self.feeds = feeds
        self.climb = climb
        self.angle = ramp_angle_deg
        self.r = ctx.tool.radius
        self.tol = ctx.tolerance_mm
        self.heights = ctx.heights
        self.eps = max(3.0 * self.tol, 0.05 * stepover)
        self.state = {"entries": {"helix": 0, "ramp": 0, "plunge": 0, "air": 0}, "passes": 0, "lifts": 0,
                      "narrow": 0, "full_slot": 0.0, "skipped": 0, "cut": []}

    # --- a level -------------------------------------------------------------------------------------------------

    def level(self, area, standing, z: float, z_prev: float, previous_area) -> bool:
        """Clear ``area`` (tool-centre space) at ``z`` where ``standing`` (WCS XY; None: everything) has material.
        False when there is nothing to cut at this level (it is skipped)."""
        import shapely

        from cadgen._internal.cam import geom2d, linking

        if standing is None:
            air = shapely.Polygon()
            todo = area
        else:
            reach = geom2d.offset(standing, self.r, tolerance=self.tol) if not standing.is_empty else standing
            todo = area.intersection(reach) if not reach.is_empty else shapely.Polygon()
            air = area.difference(reach) if not reach.is_empty else area
        if todo.is_empty or todo.area < 1e-6:
            self.state["skipped"] += 1
            return False
        pieces = [piece for piece in geom2d.polygons_of(area) if piece.intersects(todo)
                  and piece.intersection(todo).area >= 1e-6]
        pieces = linking.order_nearest(pieces, self.b.pos, key=lambda p: (p.centroid.x, p.centroid.y))
        for piece in pieces:
            seed = air.intersection(piece) if not air.is_empty else shapely.Polygon()
            self._clear(piece, seed, air, z, z_prev, previous_area)
            self.b.rapid(z=min(self.heights.retract, z + 1.0))
        return True

    def _clear(self, piece, seed, air, z, z_prev, previous_area) -> None:
        """Clear one connected piece at level ``z``, from the air in it (``seed``) or from an entry."""
        import numpy as np
        import shapely

        from cadgen._internal.cam import geom2d, linking
        from cadgen._internal.cam.operations._milling2d import ramp_along, rotate_to_nearest

        b, r, tol, heights, feeds = self.b, self.r, self.tol, self.heights, self.feeds
        state = self.state
        state["cut"] = []
        if not seed.is_empty and seed.area >= 1e-6:
            cleared = seed
        else:
            circle = shapely.maximum_inscribed_circle(piece, tolerance=max(tol, 0.01))
            coords = np.asarray(circle.coords)
            centre = coords[0]
            inscribed = float(np.hypot(*(coords[1] - coords[0]))) if len(coords) > 1 else 0.0
            helix_r = min(0.75 * r, 0.9 * inscribed)
            start = (float(centre[0]) + helix_r, float(centre[1]))
            cleared_above = previous_area is not None and previous_area.buffer(1e-6).contains(shapely.Point(start))
            z_from = z_prev if cleared_above else heights.stock_top
            if helix_r >= 0.1 * r:
                self._go(start, z_from)
                linking.helix(b, (float(centre[0]), float(centre[1])), helix_r, z_from, z, angle_deg=self.angle,
                              f=feeds.ramp_mm_min, clockwise=not self.climb)
                state["entries"]["helix"] += 1
                cleared = shapely.Point(centre).buffer(helix_r, quad_segs=geom2d.quad_segs(max(helix_r, tol), tol))
                state["cut"] = [cleared.exterior]
                cleared = cleared.intersection(piece)
            else:
                state["narrow"] += 1
                ring = rotate_to_nearest(geom2d.rings(piece, climb=self.climb)[0], b.pos)
                self._go((float(ring[0][0]), float(ring[0][1])), z_from)
                if ramp_along(b, ring, z_from, z, angle_deg=self.angle, f=feeds.ramp_mm_min):
                    state["entries"]["ramp"] += 1
                else:
                    b.feed(z=z_from, f=feeds.ramp_mm_min)
                    b.plunge(z=z, f=feeds.plunge_mm_min)
                    state["entries"]["plunge"] += 1
                b.polyline(np.column_stack([ring[1:], np.full(len(ring) - 1, z)]), f=feeds.feed_mm_min)
                # Round a piece too narrow for a helix the tool cuts its full width.
                state["full_slot"] += float(shapely.LineString(ring).length)
                cleared = piece.intersection(shapely.LineString(ring).buffer(min(self.stepover, r) * 0.5))
                state["cut"] = [shapely.LineString(ring)]
        air_here = air.buffer(self.eps) if not air.is_empty else air
        runs, bands = self._grow(piece, cleared)
        self._schedule(runs, bands, cleared, z, z_prev, previous_area, air_here)

    # --- growing the cleared area, then cutting it in a good order ---------------------------------------------------

    def _grow(self, piece, cleared):
        """Every stretch that clears ``piece`` from ``cleared``, step by step, and the new band of each step.

        Each stretch is a dict: ``kind``, ``points``, ``ring`` (its ring's points), ``step``, ``line``, ``before``
        (the area cleared before its step) and ``grown``. Each band is ``[polygon, stretches bordering it]``: the
        material a step clears between its stretches and the area cleared before it, cut once they all are."""
        import shapely

        from cadgen._internal.cam import geom2d

        tol = self.tol
        runs: list[dict] = []
        bands: list[list] = []
        for step in range(20000):
            grown = geom2d.offset(cleared, self.stepover, tolerance=tol).intersection(piece)
            grown = shapely.union_all([p for p in geom2d.polygons_of(grown) if p.intersects(cleared)])
            grown = grown.simplify(tol * 0.5).intersection(piece)
            if grown.is_empty or grown.difference(cleared).area < 1e-3:
                break
            first = len(runs)
            for ring in geom2d.rings(grown, climb=self.climb):
                for kind, points, whole in self._new_runs(ring, cleared):
                    line = shapely.LineString(points) if len(points) > 1 else shapely.Point(points[0])
                    runs.append({"kind": kind, "points": points, "ring": whole, "step": step, "line": line,
                                 "before": cleared, "grown": grown})
            for polygon in geom2d.polygons_of(grown.difference(cleared)):
                members = {i for i in range(first, len(runs)) if runs[i]["line"].distance(polygon) <= self.eps}
                bands.append([polygon, members])
            cleared = shapely.union_all([cleared, grown])
        return runs, bands

    def _schedule(self, runs, bands, start, z, z_prev, previous_area, air) -> None:
        """Cut ``runs``, the nearest one the tool may cut next each time.

        A stretch may be cut once every stretch of an earlier step within twice the tool's radius is: everything its
        tool circle can reach that an earlier step cleared is then cut, so it meets only its own band, at most a
        stepover wide. That leaves the tool free to carry one side of a pocket on for many steps before it crosses to
        the other. The tool feeds between stretches at depth only through bands whose stretches are all cut."""
        import numpy as np
        import shapely

        if not runs:
            return
        reach = 2.0 * self.r + self.eps
        tree = shapely.STRtree([run["line"] for run in runs])
        waiting = [0] * len(runs)
        dependents: list[list[int]] = [[] for _ in runs]
        for i, run in enumerate(runs):
            for j in tree.query(run["line"], predicate="dwithin", distance=reach):
                if runs[int(j)]["step"] < run["step"]:
                    waiting[i] += 1
                    dependents[int(j)].append(i)
        of_run: list[list[int]] = [[] for _ in runs]
        left = []
        done = start
        for k, (polygon, members) in enumerate(bands):
            left.append(len(members))
            for i in members:
                of_run[i].append(k)
            if not members:
                done = shapely.union_all([done, polygon])
        ready = {i for i, count in enumerate(waiting) if count == 0}
        b = self.b
        while ready:
            here = np.asarray(b.pos[:2])
            i = min(ready, key=lambda k: _distance_to_start(runs[k], here))
            ready.discard(i)
            run = runs[i]
            points = self._spiral(run["points"], run["before"]) if run["kind"] == "loop" else run["points"]
            own = shapely.union_all([done] + [bands[k][0] for k in of_run[i]])
            self._cut(points, z, z_prev, previous_area, done.buffer(self.eps), own.buffer(1e-6), air, run["ring"])
            for k in of_run[i]:
                left[k] -= 1
                if left[k] == 0:
                    done = shapely.union_all([done, bands[k][0]])
            for j in dependents[i]:
                waiting[j] -= 1
                if waiting[j] == 0:
                    ready.add(j)

    # --- the stretches of a boundary that reach new material --------------------------------------------------------

    def _new_runs(self, ring, cleared) -> list:
        """The stretches of ``ring`` off ``cleared``, each ``(kind, points, the ring's points)``: ``"loop"`` for a
        ring wholly in new material (entered anywhere, by a spiral off the cleared edge), else ``"open"`` per stretch,
        widened by one point at either end so it starts and ends on cleared."""
        import numpy as np
        import shapely

        line = shapely.segmentize(shapely.LineString(ring), max(0.05, self.stepover / 2.0))
        points = np.asarray(line.coords)[:-1]
        if len(points) < 3:
            return []
        new = shapely.distance(shapely.points(points), cleared) > self.eps
        if not new.any():
            return []
        if new.all():
            return [("loop", points, points)]
        n = len(points)
        runs, current = [], []
        first = int(np.argmin(new))         # a cleared point to start the walk from
        order = np.roll(np.arange(n), -first)
        for index in order:
            if new[index]:
                if not current:
                    current.append((index - 1) % n)
                current.append(index)
            elif current:
                current.append(index)
                runs.append(("open", points[current], points))
                current = []
        if current:
            current.append(order[0])
            runs.append(("open", points[current], points))
        return runs

    def _spiral(self, points, cleared):
        """A ring wholly in new material (the first round an entry), started nearest the tool: spiral out onto it
        from the cleared edge over its first stretch, so the engagement grows from nothing, then once round it."""
        import numpy as np
        import shapely

        b = self.b
        k = int(np.argmin(np.hypot(points[:, 0] - b.pos[0], points[:, 1] - b.pos[1])))
        loop = np.vstack([points[k:], points[:k], points[k:k + 1]])
        along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(loop, axis=0).T))])
        stretch = min(along[-1] / 4.0, max(3.0 * self.stepover, along[-1] / 8.0))
        q = max(1, int(np.searchsorted(along, stretch)))
        edge = cleared.boundary
        spiral = []
        for i in range(q + 1):
            t = along[i] / along[q]
            on_edge = edge.interpolate(edge.project(shapely.Point(loop[i])))
            spiral.append((1.0 - t) * np.array([on_edge.x, on_edge.y]) + t * loop[i])
        return np.vstack([np.asarray(spiral), loop[q + 1:], loop[1:q + 1]])

    # --- getting there and cutting --------------------------------------------------------------------------------

    def _go(self, start, z_from) -> None:
        """Over ``start`` by the clearance plane, down to the retract plane, then to 1 mm over ``z_from``."""
        b, heights = self.b, self.heights
        if b.pos[2] < heights.retract - 1e-9:
            b.rapid(z=heights.retract)
        if (abs(b.pos[0] - start[0]) > 1e-9) or (abs(b.pos[1] - start[1]) > 1e-9):
            if b.pos[2] < heights.clearance - 1e-9:
                b.rapid(z=heights.clearance)
            b.rapid(x=start[0], y=start[1])
        b.rapid(z=heights.retract)
        if z_from + 1.0 < heights.retract:
            b.rapid(z=z_from + 1.0)

    def _cut(self, run, z, z_prev, previous_area, safe, band, air, ring) -> None:
        """To the start of ``run`` and along it at ``z``. A stretch the tool cannot reach at depth through cleared
        space is come back to from the retract plane: straight down where its start is in the air, else ramped into
        along itself (never fed straight down into material)."""
        import numpy as np
        import shapely

        from cadgen._internal.cam.operations._milling2d import ramp_along

        b, heights, feeds, state, r = self.b, self.heights, self.feeds, self.state, self.r
        target = (float(run[0][0]), float(run[0][1]))
        step = shapely.LineString([b.pos[:2], target])
        down = abs(b.pos[2] - z) < 1e-9
        if down and step.length <= 1.5 * self.stepover and step.within(band):
            # A step of at most a stepover into the new band (onto the first ring round an entry).
            b.feed(x=target[0], y=target[1], z=z, f=feeds.ramp_mm_min)
        elif down and (step.length < 1e-9 or step.within(safe.buffer(1e-6))):
            b.feed(x=target[0], y=target[1], z=z, f=feeds.feed_mm_min)
        else:
            state["lifts"] += 1
            b.rapid(z=heights.retract)
            b.rapid(x=target[0], y=target[1])
            point = shapely.Point(target)
            if not air.is_empty and air.contains(point):
                # Nothing stands round the tool here at this level, nor above it: straight down through air.
                if z + 1.0 < heights.retract:
                    b.rapid(z=z + 1.0)
                b.feed(z=z, f=feeds.plunge_mm_min)
                state["entries"]["air"] += 1
            else:
                above = previous_area is not None and previous_area.buffer(1e-6).contains(point)
                z_from = z_prev if above else heights.stock_top
                if z_from + 1.0 < heights.retract:
                    b.rapid(z=z_from + 1.0)
                circle = point.buffer(r * 0.999, quad_segs=16)
                near = [line for line in state["cut"] if line.distance(point) <= 2.0 * r]
                if near and circle.difference(shapely.union_all([line.buffer(r, quad_segs=16)
                                                                 for line in near])).area < 1e-3:
                    # This level is cut all round the tool there already: straight down through air.
                    b.feed(z=z, f=feeds.plunge_mm_min)
                else:
                    k = int(np.argmin(np.hypot(ring[:, 0] - target[0], ring[:, 1] - target[1])))
                    around = np.vstack([[target], ring[k:], ring[:k + 1]])
                    if ramp_along(b, run, z_from, z, angle_deg=self.angle, f=feeds.ramp_mm_min) or ramp_along(
                            b, around, z_from, z, angle_deg=self.angle, f=feeds.ramp_mm_min):
                        state["entries"]["ramp"] += 1
                    else:
                        b.feed(z=z_from, f=feeds.ramp_mm_min)
                        b.plunge(z=z, f=feeds.plunge_mm_min)
                        state["entries"]["plunge"] += 1
        b.polyline(np.column_stack([run[1:], np.full(len(run) - 1, z)]), f=feeds.feed_mm_min)
        state["cut"].append(shapely.LineString(run) if len(run) > 1 else shapely.Point(run[0]))
        state["passes"] += 1

    def meta(self) -> dict:
        """The plain facts of the clearing, for the operation's meta."""
        state = self.state
        out = {"entries": {k: v for k, v in state["entries"].items() if v}, "passes": state["passes"],
               "full_slot_mm": round(state["full_slot"], 3)}
        if state["skipped"]:
            out["levels_already_clear"] = state["skipped"]
        return out


def _distance_to_start(run, here) -> float:
    """How far the tool is from where it would start ``run``: its first point, or a loop's nearest."""
    import numpy as np

    kind, points = run["kind"], run["points"]
    if kind == "loop":
        return float(np.min(np.hypot(points[:, 0] - here[0], points[:, 1] - here[1])))
    return float(np.hypot(points[0][0] - here[0], points[0][1] - here[1]))
