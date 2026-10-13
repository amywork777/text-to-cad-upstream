"""Posts past GRBL (track B3): a golden per post and machine kind on a small hand-built IR, every program read back to
the IR's own path, the dialect words each controller needs, and the teaching refusals."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

import numpy as np

from cadgen._internal.cam.ir import ARC_CCW, ARC_CW, DWELL
from cadgen._internal.cam.job import parse_job
from cadgen._internal.cam.job_errors import CamJobError
from cadgen._internal.cam.posts import POST_NAMES, REGISTRY, available, get_post
from tests.python.support import cam_fixtures_posts as F
from tests.python.support import gcode_reader

GOLDENS = Path(__file__).with_name("goldens")

#: (post, fixture kind, machine keys, golden name)
CASES = [
    ("linuxcnc", "mill", {}, "mill"),
    ("linuxcnc", "mill4", {}, "mill4"),
    ("linuxcnc", "mill4_wrap", {}, "mill4_wrap"),
    ("linuxcnc", "mill5", {}, "mill5"),
    ("linuxcnc", "mill5_tcp", {}, "mill5_tcp"),
    ("linuxcnc", "lathe", {}, "lathe"),
    ("fanuc", "mill", {}, "mill"),
    ("fanuc", "mill4", {}, "mill4"),
    ("fanuc", "mill5", {}, "mill5"),
    ("fanuc", "mill5_tcp", {}, "mill5_tcp"),
    ("fanuc", "lathe", {}, "lathe"),
    ("fanuc", "lathe", {"cycles": True, "program_number": 42}, "lathe_cycles"),
    ("haas", "mill", {"smoothing": "medium"}, "mill"),
    ("haas", "mill5", {}, "mill5"),
    ("haas", "mill5_tcp", {}, "mill5_tcp"),
    ("haas", "lathe", {}, "lathe"),
    ("haas", "lathe", {"cycles": True}, "lathe_cycles"),
    ("mach3", "mill", {}, "mill"),
    ("mach3", "mill4", {}, "mill4"),
    ("mach3", "router", {"cycles": False}, "router_expanded"),
    ("mach3", "plasma", {"thc": True, "dwell_ms": True}, "plasma"),
    ("marlin", "laser", {}, "laser"),
    ("marlin", "laser", {"laser_scale": 1000, "inline_power": True}, "laser_inline"),
    ("plasma", "plasma", {}, "plasma"),
    ("waterjet", "waterjet", {}, "waterjet"),
    ("wire_edm", "wire_edm", {}, "wire_edm"),
]
_KIND = {"mill5_tcp": "mill5", "mill4_wrap": "mill4"}


def render(post_name: str, kind: str, keys: dict):
    program = F.program(kind, post_name, keys)
    post = get_post(post_name, _KIND.get(kind, kind))
    return post, program, post.render(program)


def _nearest(a: np.ndarray, b: np.ndarray) -> float:
    """The largest distance from a point of ``a`` to the polyline through ``b`` (consecutive points joined)."""
    if not len(a):
        return 0.0
    if len(b) == 1:
        return float(np.linalg.norm(a - b[0], axis=1).max())
    p0, p1 = b[:-1], b[1:]
    d = p1 - p0
    length2 = np.maximum((d * d).sum(axis=1), 1e-18)
    best = np.full(len(a), np.inf)
    for chunk in range(0, len(a), 512):
        q = a[chunk:chunk + 512][:, None, :]
        t = np.clip(((q - p0[None]) * d[None]).sum(axis=2) / length2[None], 0.0, 1.0)
        gap = np.linalg.norm(q - (p0[None] + t[..., None] * d[None]), axis=2).min(axis=1)
        best[chunk:chunk + 512] = gap
    return float(best.max())


def read_back(post, program, text):
    machine = program.machine
    lathe = machine.kind == "lathe"
    start = program.toolpath.start
    if machine.kind == "wire_edm":
        start = (0.0, 0.0, 0.0)
    return gcode_reader.read(text, start=start, lathe=lathe, diameter=getattr(machine, "diameter_mode", True))


class Goldens(unittest.TestCase):
    def test_every_post_and_kind_matches_its_golden(self):
        for post_name, kind, keys, golden in CASES:
            with self.subTest(post=post_name, case=golden):
                _, _, text = render(post_name, kind, keys)
                path = GOLDENS / post_name / f"{golden}.nc"
                if not path.exists() or os.environ.get("CAM_UPDATE_GOLDENS"):  # pragma: no cover - (re)writes it
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                self.assertEqual(text, render(post_name, kind, keys)[2], "posting is deterministic")

    def test_every_registered_post_is_built_and_opens_with_the_safety_block(self):
        self.assertEqual([name for name in POST_NAMES if not available(name)], [])
        for post_name, kind, keys, golden in CASES:
            with self.subTest(post=post_name, case=golden):
                text = render(post_name, kind, keys)[2].upper()
                head = "\n".join(text.splitlines()[:8])
                self.assertIn("NOT PROVEN ON A MACHINE", head)
                self.assertIn("AIR-CUT IT OR RUN IT SINGLE-BLOCK FIRST", head)
                self.assertIn("VERIFY THE WORK OFFSET", head)
                self.assertTrue(text.isascii())


class ReadBack(unittest.TestCase):
    """Every posted program, read by a controller-like reader, retraces the IR (native cycles the reader cannot
    expand are checked by their parameters instead)."""

    def _ir_points(self, program, post, masked_kinds, step=None):
        path = program.toolpath
        samples = path.sample(0.002, max_step_mm=step)
        keep = np.ones(len(samples.points), dtype=bool)       # the start too: a G43 Z line can sit on it
        for event in path.events:
            if event.kind == "cycle" and event.data.get("cycle") in masked_kinds and post.emits_cycle(event.data):
                keep &= ~((samples.move >= event.at) & (samples.move < event.data["end"]))
        if program.machine.kind == "wire_edm":
            first_cut = next(i for i in range(len(path.moves)) if path.moves[i]["kind"] != 0)
            before = samples.move < first_cut
            keep &= ~before
            keep[int(np.nonzero(before)[0].max())] = True          # where the wire is threaded
        return samples.points[keep]

    def test_the_posted_path_is_the_ir_path(self):
        for post_name, kind, keys, golden in CASES:
            with self.subTest(post=post_name, case=golden):
                post, program, text = render(post_name, kind, keys)
                read = read_back(post, program, text)
                # Dense points of one path against the polyline of the other, both ways.
                dense, _ = gcode_reader.sample(read, 0.002, max_step=0.25)
                line, _ = gcode_reader.sample(read, 0.002)
                begin = program.toolpath.start if program.machine.kind != "wire_edm" else (*read.g92[0], 0.0)
                dense, line = np.vstack([begin, dense]), np.vstack([begin, line])
                masked = ("thread", "turn_rough")
                ir_dense = self._ir_points(program, post, masked, 0.25)
                ir_line = self._ir_points(program, post, masked)
                planar = program.machine.kind in ("laser", "plasma", "waterjet", "wire_edm")
                if planar:
                    dense, line, ir_dense, ir_line = (a[:, :2] for a in (dense, line, ir_dense, ir_line))
                self.assertLess(_nearest(ir_dense, line), 0.012, "every IR point is on the posted path")
                if not read.threads and not read.roughs:
                    self.assertLess(_nearest(dense, ir_line), 0.012, "every posted point is on the IR path")
                points = line
                if not planar:
                    self.assertTrue(np.allclose(points[-1], program.toolpath.ends()[-1], atol=1e-3))

    def test_lathe_cycles_read_back_to_their_parameters(self):
        for post_name in ("linuxcnc", "fanuc", "haas"):
            with self.subTest(post=post_name):
                post, program, text = render(post_name, "lathe", {})
                read = read_back(post, program, text)
                self.assertEqual(len(read.threads), 1)
                thread = read.threads[0]
                self.assertAlmostEqual(thread["root"], F.THREAD["x_crest"] - F.THREAD["depth_mm"], places=3)
                self.assertAlmostEqual(thread["depth"], F.THREAD["depth_mm"], places=3)
                self.assertAlmostEqual(thread["pitch"], F.THREAD["pitch_mm"], places=4)
                self.assertAlmostEqual(thread["z_end"], F.THREAD["z_end"], places=4)
                self.assertAlmostEqual(thread["x_clear"], F.THREAD["x_clear"], places=4)
                self.assertEqual(read.roughs, [], "roughing posts expanded unless machine.cycles is true")
                points, _ = gcode_reader.sample(read, 0.002, max_step=0.05)
                ir = self._ir_points(program, post, ("thread",))
                self.assertLess(_nearest(points, program.toolpath.sample(0.002, max_step_mm=0.05).points), 0.035,
                                "the thread's final pass is the IR's last pass")
        for post_name in ("fanuc", "haas"):
            with self.subTest(post=post_name, cycles=True):
                post, program, text = render(post_name, "lathe", {"cycles": True})
                read = read_back(post, program, text)
                self.assertEqual(len(read.roughs), 1)
                rough = read.roughs[0]
                # The first profile block moves X only (Fanuc type I), from the cycle's start Z.
                self.assertEqual([tuple(float(v) for v in np.round(p, 6)) for p in rough["profile"]],
                                 [(F.ROUGH["profile"][0][0], F.ROUGH["z_start"])]
                                 + [tuple(p) for p in F.ROUGH["profile"]])
                self.assertAlmostEqual(rough["depth"], F.ROUGH["depth_mm"])
                self.assertAlmostEqual(abs(rough["u"]), 2 * F.ROUGH["allowance_x_mm"])

    def test_rotary_words_follow_the_ir(self):
        for post_name, kind in (("linuxcnc", "mill5_tcp"), ("fanuc", "mill5_tcp"), ("haas", "mill5_tcp"),
                                ("linuxcnc", "mill4_wrap")):
            with self.subTest(post=post_name, kind=kind):
                post, program, text = render(post_name, kind, {})
                read = read_back(post, program, text)
                moves = program.toolpath.moves
                ir = [tuple(np.round([m["x"], m["y"], m["z"], m["a"], m["b"], m["c"]], 4)) for m in moves
                      if int(m["kind"]) != DWELL]
                posted = [tuple(np.round([*mv.end, mv.abc["A"], mv.abc["B"], mv.abc["C"]], 4)) for mv in read.moves
                          if mv.kind != "dwell"]
                dedupe = lambda rows: [r for k, r in enumerate(rows) if k == 0 or r != rows[k - 1]]  # noqa: E731
                self.assertEqual(dedupe(ir), dedupe(posted))
                self.assertFalse(any(m.kind in ("arc_cw", "arc_ccw") for m in read.moves))
                self.assertEqual(read.tcp, [post.tcp_code] if kind == "mill5_tcp" else ["G43.4"])

    def test_tilted_setups_turn_the_table_after_each_tool_change(self):
        for post_name, words in (("linuxcnc", "G0 A30 C90"), ("haas", "G0 A30. C90.")):
            with self.subTest(post=post_name):
                text = render(post_name, "mill5", {})[2]
                lines = text.splitlines()
                for k, line in enumerate(lines):
                    if re.match(r"T\d+ M0?6$", line):
                        self.assertEqual(lines[k + 1], words)
                if post_name == "haas":
                    self.assertEqual(lines.count("G254"), 3)
                    self.assertEqual(lines.count("G255"), 3)
        text = render("fanuc", "mill5", {})[2]
        read = gcode_reader.read(text, start=(0, 0, 5))
        self.assertEqual(len(read.tilt), 3)
        self.assertEqual(read.tilt[0], {"X": 0.0, "Y": 0.0, "Z": 0.0, "I": -90.0, "J": -30.0, "K": 0.0})
        self.assertEqual(text.count("G69"), 3)
        self.assertNotIn(" A", text.split("G21", 1)[1])          # G68.2 turns the table: no A/C words posted


class Dialects(unittest.TestCase):
    def test_fanuc_and_haas_write_decimal_points_percent_and_an_o_number(self):
        for post_name, o_line in (("fanuc", "O1000 "), ("haas", "O01000 ")):
            for kind in ("mill", "lathe"):
                with self.subTest(post=post_name, kind=kind):
                    text = render(post_name, kind, {})[2]
                    lines = text.splitlines()
                    self.assertEqual(lines[0], "%")
                    self.assertEqual(lines[-1], "%")
                    self.assertTrue(lines[1].startswith(o_line))
                    code = [re.sub(r"\([^)]*\)", "", line) for line in lines]
                    for line in code:
                        for word in re.findall(r"\b([XYZIJKRQUWABC])(-?[\d.]+)", line):
                            if line.startswith("G76"):           # its P and Q are microns, A an angle
                                continue
                            self.assertIn(".", word[1], f"{word} in {line!r}")
        self.assertTrue(render("fanuc", "lathe", {"cycles": True, "program_number": 42})[2].splitlines()[1]
                        .startswith("O0042 "))

    def test_fanuc_comments_are_upper_case_and_the_lathe_has_no_g90(self):
        text = render("fanuc", "lathe", {})[2]
        for comment in re.findall(r"\(([^)]*)\)", text):
            self.assertEqual(comment, comment.upper())
        self.assertNotIn("G90", text)                   # a turning cycle in G-code system A
        self.assertIn("T0101", text)
        self.assertIn("G50 S3000", text)
        self.assertIn("G96 S200 M3", text)
        self.assertIn("G99", text)
        self.assertIn("G76 P010060 Q50 R0.", text)
        self.assertIn("G76 X8.78 Z-15. P610 Q250 F1.", text)
        self.assertIn("G2 X12. Z-10. I2. K0.", text)    # X a diameter, I a radius

    def test_linuxcnc_lathe_and_tapping(self):
        text = render("linuxcnc", "lathe", {})[2]
        self.assertIn("G7", text.splitlines())
        self.assertIn("G96 D3000 S200 M3", text)
        self.assertIn("G95", text)
        self.assertIn("G76 P1 Z-15 I-2 J0.5 K1.22 R2 Q29.5 H1", text)
        radius = render("linuxcnc", "lathe", {"diameter_mode": False})[2]
        self.assertIn("G8", radius.splitlines())
        self.assertIn("G2 X6 Z-10 I2 K0", radius)
        mill = render("linuxcnc", "mill", {})[2]
        self.assertIn("G33.1 Z-8 K1", mill)
        self.assertNotIn("G84", mill)
        self.assertIn("G98 G83 X-10 Y5 Z-6 R1 Q3 F300", mill)
        self.assertTrue(mill.rstrip().endswith("M2"))

    def test_fanuc_rigid_taps_with_m29_and_haas_without(self):
        self.assertIn("M29 S500\nG99 G84", render("fanuc", "mill", {})[2])
        haas = render("haas", "mill", {"smoothing": "medium"})[2]
        self.assertNotIn("M29", haas)
        self.assertIn("G99 G84 X-10. Y5. Z-8. R2. F500.", haas)
        self.assertIn("G187 P2 E0.01", haas)
        self.assertIn("T1 M06", haas)

    def test_cycles_false_posts_every_cycle_as_moves(self):
        for post_name in ("linuxcnc", "fanuc", "haas", "mach3"):
            with self.subTest(post=post_name):
                text = render(post_name, "mill", {"cycles": False})[2]
                self.assertNotRegex(text, r"\bG8[1-9]\b|G73|G33\.1")
                if post_name != "mach3":
                    lathe = render(post_name, "lathe", {"cycles": False})[2]
                    self.assertNotIn("G76", lathe)
                    self.assertNotIn("G71", lathe)

    def test_mach3_sets_incremental_arc_centres_and_dwells_in_seconds(self):
        text = render("mach3", "mill", {})[2]
        self.assertIn("G91.1", text)
        self.assertIn("G4 P0.5", text)
        self.assertIn("G98 G83", text)
        self.assertIn("G4 P500", render("mach3", "mill", {"dwell_ms": True})[2])

    def test_torch_sequence(self):
        text = render("plasma", "plasma", {})[2]
        self.assertIn("G0 Z3.8\nM3\nG4 P0.4\nG1 Z1.5 F1000\nM101\n", text)
        self.assertIn("M102\nM5\nG0 Z10\n", text)
        quiet = render("plasma", "plasma", {"thc": False, "torch_z": False, "pierce_delay_s": 1.5})[2]
        self.assertNotIn("M101", quiet)
        self.assertNotIn("Z", "\n".join(l for l in quiet.splitlines() if not l.startswith("(")))
        mach = render("mach3", "plasma", {})[2]
        self.assertNotIn("M101", mach)                 # THC is off by default on Mach3
        self.assertIn("M3\nG4 P0.4", mach)

    def test_marlin_scales_power_and_never_ends_with_m30(self):
        text = render("marlin", "laser", {})[2]
        self.assertIn("M3 S204", text)                  # 0.8 of 255
        self.assertNotIn("M30", text)
        self.assertNotIn("G54", text.replace("; Verify the work offset G54", ""))
        self.assertIn("M8", text)                       # air assist
        inline = render("marlin", "laser", {"laser_scale": 1000, "inline_power": True})[2]
        self.assertIn("M3 I S0", inline)
        self.assertIn("G1 X5 S800 F1500", inline)
        self.assertIn("G0 S0\nX-15 Y-15", inline)
        self.assertNotIn("Z", "\n".join(l for l in text.splitlines() if not l.startswith(";")))
        dynamic = render("marlin", "laser", {"laser_mode": "dynamic"})[2]
        self.assertIn("M4 S204", dynamic)

    def test_waterjet_jet_words(self):
        text = render("waterjet", "waterjet", {})[2]
        self.assertIn("M3\nG4 P0.4\nG1 X5 F1500", text)
        self.assertEqual(text.count("M5"), 2)

    def test_wire_edm_start_point_threading_and_taper(self):
        text = render("wire_edm", "wire_edm", {})[2]
        self.assertIn("G92 X0. Y0.", text)
        self.assertIn("M60\nG0 X-15. Y-15.\n(THREAD THE WIRE)\nM50", text)
        self.assertIn("WIRE CENTRE", text)
        self.assertNotRegex(text, r"\bZ-?\d")
        tapered = F.wire({"uv_words": False}, beam={"taper_deg": 2.0, "thickness_mm": 20.0})
        g51 = get_post("wire_edm", "wire_edm").render(tapered)
        self.assertEqual(g51.count("G51 A2."), 2)
        self.assertEqual(g51.count("G50"), 3)          # the preamble's cancel and one per cut
        uv = get_post("wire_edm", "wire_edm").render(F.wire({"uv_words": True},
                                                            beam={"taper_deg": 2.0, "thickness_mm": 20.0}))
        read = gcode_reader.read(uv)
        lean = 20.0 * np.tan(np.radians(2.0))
        leans = [np.hypot(*m.uv) for m in read.moves if m.uv is not None and m.kind == "feed" and any(m.uv)]
        self.assertTrue(leans)
        self.assertTrue(np.allclose(leans, lean, atol=2e-3))
        # The square's first side runs +X: the wire's top leans to its left, +Y.
        side = next(m for m in read.moves if m.uv and m.start[1] == -12.0 and m.end == (12.0, -12.0, 0.0))
        self.assertAlmostEqual(side.uv[1], lean, places=3)
        self.assertNotIn("G2 ", uv)
        self.assertNotIn("G3 ", uv)
        comp = get_post("wire_edm", "wire_edm").render(F.wire({"wire_comp": "controller"},
                                                              beam={"offset_side": "left"}))
        self.assertEqual(comp.count("G41 D1"), 2)


    def test_a_skim_pass_keeps_the_wire_threaded(self):
        from dataclasses import replace

        from cadgen._internal.cam.ir import ToolpathBuilder

        base = F.wire()
        b = ToolpathBuilder((0, 0, 0))
        b.event("tool", tool="W1", number=1)
        for label in ("rough", "skim"):              # the same start hole, a pass and a skim
            b.event("beam", on=True, offset_side="left", **{"pass": label})
            b.feed(x=5, y=0, f=300)
            b.arc(5, 0, 0, centre=(0, 0, 0), clockwise=False, f=300)
            b.feed(x=0, y=0, f=300)
            b.event("beam", on=False)
        text = get_post("wire_edm", "wire_edm").render(replace(base, toolpath=b.build()))
        self.assertNotIn("M60", text)
        self.assertNotIn("M50", text)

    def test_a_radial_thread_infeed_posts_a_zero_tip_angle(self):
        from dataclasses import replace

        from cadgen._internal.cam.ir import Event, Toolpath

        program = F.lathe("fanuc")
        events = [Event(e.at, e.kind, {**e.data, "infeed_deg": 0.0} if e.data.get("cycle") == "thread" else e.data)
                  for e in program.toolpath.events]
        path = Toolpath(program.toolpath.moves, events, program.toolpath.ops, start=program.toolpath.start, lathe=True)
        self.assertIn("G76 P010000 Q50", get_post("fanuc", "lathe").render(replace(program, toolpath=path)))
        haas = F.lathe("haas")
        path = Toolpath(haas.toolpath.moves, events, haas.toolpath.ops, start=haas.toolpath.start, lathe=True)
        self.assertRegex(get_post("haas", "lathe").render(replace(haas, toolpath=path)), r"G76 .* A0\n")


class Refusals(unittest.TestCase):
    def assertRefuses(self, call, *fragments):
        with self.assertRaises(CamJobError) as caught:
            call()
        for fragment in fragments:
            self.assertIn(fragment, str(caught.exception))

    def test_events_a_machine_cannot_run(self):
        from cadgen._internal.cam.ir import Event, Toolpath

        program = F.mill("fanuc")
        path = program.toolpath
        beam = Toolpath(path.moves, list(path.events) + [Event(3, "beam", {"on": True})], path.ops, start=path.start)
        self.assertRefuses(lambda: get_post("fanuc", "mill").render(_with(program, beam)), "no beam")
        cut = F.cutting("plasma", "plasma")
        spun = Toolpath(cut.toolpath.moves, list(cut.toolpath.events) + [Event(1, "spindle", {"rpm": 100})],
                        (), start=cut.toolpath.start)
        self.assertRefuses(lambda: get_post("plasma", "plasma").render(_with(cut, spun)), "starts a spindle")
        wet = Toolpath(cut.toolpath.moves, list(cut.toolpath.events) + [Event(1, "coolant", {"mode": "flood"})],
                       (), start=cut.toolpath.start)
        self.assertRefuses(lambda: get_post("plasma", "plasma").render(_with(cut, wet)), "no coolant")
        wire = F.wire()
        drill = Toolpath(wire.toolpath.moves, list(wire.toolpath.events) + [Event(1, "cycle", {"cycle": "drill"})],
                         (), start=wire.toolpath.start)
        self.assertRefuses(lambda: get_post("wire_edm", "wire_edm").render(_with(wire, drill)), "drilling cycle")

    def test_axes_a_machine_does_not_have(self):
        wrap = F.simultaneous("fanuc", "mill5", "ac")
        three = F.mill("fanuc")
        from dataclasses import replace

        self.assertRefuses(lambda: get_post("fanuc", "mill").render(replace(wrap, machine=three.machine)),
                           "turns the A axis", "XYZ")
        bc = F.simultaneous("haas", "mill5", "bc")
        ac = F.simultaneous("haas", "mill5", "ac")
        self.assertRefuses(lambda: get_post("haas", "mill5").render(replace(bc, machine=ac.machine)),
                           "turns the B axis")
        lathe = F.lathe("fanuc")
        moves = lathe.toolpath.moves.copy()
        moves["y"][5] = 1.0
        from cadgen._internal.cam.ir import Toolpath

        off = Toolpath(moves, lathe.toolpath.events, lathe.toolpath.ops, start=lathe.toolpath.start, lathe=True)
        self.assertRefuses(lambda: get_post("fanuc", "lathe").render(_with(lathe, off)), "off the XZ plane")

    def test_wire_options_that_need_more_from_the_cut(self):
        self.assertRefuses(lambda: get_post("wire_edm", "wire_edm").render(F.wire({"wire_comp": "controller"})),
                           "which side")
        self.assertRefuses(lambda: get_post("wire_edm", "wire_edm").render(
            F.wire({"uv_words": True}, beam={"taper_deg": 2.0})), "thickness_mm")

    def test_machine_keys_belong_to_their_post(self):
        job = {"machine": {"kind": "mill", "post": "fanuc", "cycles": True, "program_number": 7},
               "material": "aluminum-6061", "stock": {"kind": "box", "margin_mm": 1},
               "tools": [{"id": "T1", "type": "flat", "diameter_mm": 6}],
               "setups": [{"id": "top", "operations": [{"op": "face", "tool": "T1"}]}]}
        parsed = parse_job(job)
        self.assertEqual(parsed.machine.post_options, {"cycles": True, "program_number": 7.0})
        self.assertEqual(parsed.machine.as_dict()["cycles"], True)
        bad = {**job, "machine": {"kind": "mill", "post": "fanuc", "laser_scale": 255}}
        self.assertRefuses(lambda: parse_job(bad), "unknown key 'laser_scale'", "cycles", "program_number")
        wrong = {**job, "machine": {"kind": "mill", "post": "fanuc", "cycles": "yes"}}
        self.assertRefuses(lambda: parse_job(wrong), "machine.cycles must be true or false")
        scale = {**job, "machine": {"kind": "laser", "post": "marlin", "laser_scale": 100}}
        self.assertRefuses(lambda: parse_job(scale), "machine.laser_scale", "255, 1000")
        big = F.mill("fanuc", {"program_number": 12345})
        self.assertRefuses(lambda: get_post("fanuc", "mill").render(big), "at most 9999")

    def test_every_post_serves_exactly_its_registered_kinds(self):
        for name, entry in REGISTRY.items():
            with self.subTest(post=name):
                post = get_post(name, entry.kinds[0])
                self.assertEqual(tuple(post.kinds), entry.kinds)
                self.assertEqual(post.extension, entry.extension)


def _with(program, path):
    from dataclasses import replace

    return replace(program, toolpath=path)


if __name__ == "__main__":
    unittest.main()
