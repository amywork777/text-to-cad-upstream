"""The pages of a work instruction: each step's picture, and the PDF.

``write_pdf`` lays the document out as pages of draw commands first, so every
page's header can say ``PAGE n OF m``, then renders them with matplotlib to a
temporary file renamed into place: a failed run leaves no document behind.

The pictures are one snapshot packet, one browser: for each step the assembly
as it stands after the step, drawn as hidden-line art -- black edges, whatever
colours the STEP carries, so the one colour on the page means what the legend
says. Parts a later step installs are hidden; parts the step installs are
filled by an area mark laid over their own triangles, and the surfaces the step
names (a bond line, a machined face) are filled in a second colour. Every
picture shares one camera fitted to the whole assembly, with tight framing off,
so a part sits in the same place on every page.
"""

from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

NEW_PART = "#1f6feb"
SURFACE = "#8250df"
PICTURE_PX = (1600, 1000)
PAGE_MM = {"A4": (210.0, 297.0), "LETTER": (215.9, 279.4)}
MARGIN = 12.0
PT = 25.4 / 72.0  # millimetres per point
BODY, SMALL, HEAD, TITLE = 8.5, 7.0, 11.0, 15.0


# --- pictures ----------------------------------------------------------------


@dataclass(frozen=True)
class Picture:
    """What one step's picture shows: by leaf occurrence ref."""

    step: int
    hide: tuple[str, ...]
    tint: tuple[str, ...]
    surfaces: tuple[str, ...]
    camera: str


def picture_plan(wi) -> list[Picture]:
    """Each step that has a picture: what it hides, tints and marks. A step with
    nothing installed yet (a preparation step before the first part) has none."""
    leaves = [leaf.ref for leaf in wi.leaves()]
    installed: set[str] = set()
    plan = []
    for step in wi.steps:
        installed.update(step.install)
        surfaces = tuple(ref for op in step.ops for ref, _owner in op.surfaces)
        for ref, owner in (pair for op in step.ops for pair in op.surfaces):
            if owner not in installed:
                raise ValueError(
                    f"step {step.number} marks {ref}, on {owner}, which is not installed by step {step.number}"
                )
        if not (wi.pictures and step.picture and installed):
            continue
        plan.append(Picture(step.number, tuple(ref for ref in leaves if ref not in installed),
                            step.install, surfaces, step.camera or wi.camera))
    return plan


def _area(mark_id: str, shape, color: str, opacity: float, tolerance: float) -> dict:
    vertices, triangles = shape.tessellate(tolerance, 0.3)
    if not triangles:
        raise ValueError(f"{mark_id}: nothing to draw -- the shape tessellated to no triangles")
    return {
        "id": mark_id, "kind": "area", "color": color, "opacity": opacity,
        "points": [round(c, 4) for v in vertices for c in (v.X, v.Y, v.Z)],
        "triangles": [i for tri in triangles for i in tri], "outline": 3,
    }


def _extent(wi) -> tuple[list[float], float]:
    """The whole assembly's centre and bounding diagonal: every picture is framed on it."""
    from build123d import Compound

    box = Compound([leaf.shape() for leaf in wi.leaves()]).bounding_box()
    centre = [(box.min.X + box.max.X) / 2, (box.min.Y + box.max.Y) / 2, (box.min.Z + box.max.Z) / 2]
    return [round(c, 4) for c in centre], math.dist((box.min.X, box.min.Y, box.min.Z),
                                                    (box.max.X, box.max.Y, box.max.Z))


def render_pictures(wi, folder: Path) -> dict[int, Path]:
    """Render every step's picture in one snapshot packet; {step number: PNG}."""
    plan = picture_plan(wi)
    if not plan:
        return {}
    from cadgen import step as step_door

    leaves = {leaf.ref: leaf for leaf in wi.leaves()}
    centre, diagonal = _extent(wi)
    tolerance = max(diagonal * 0.002, 0.01)
    jobs, out = [], {}
    for picture in plan:
        camera = {"preset": picture.camera, "target": centre, "orthographicHalfHeight": round(0.55 * diagonal, 4)}
        marks = [_area(f"step{picture.step}-{ref}", leaves[ref].shape(), NEW_PART, 0.6, tolerance)
                 for ref in picture.tint]
        marks += [_area(f"step{picture.step}-{ref}", wi.scene.resolve(ref)[0].shape(), SURFACE, 0.75, tolerance)
                  for ref in picture.surfaces]
        path = folder / f"step-{picture.step}.png"
        job = {"input": str(wi.step_path), "mode": "view", "display": "hidden-line",
               "output": {"tightFrame": False, "transparent": True},
               "outputs": [{"path": str(path), "camera": camera}]}
        if marks:
            job["annotation"] = {"units": "mm", "marks": marks}
        if picture.hide:
            job["selection"] = {"hide": list(picture.hide)}
        jobs.append(job)
        out[picture.step] = path
    packet = folder / "pictures.json"
    packet.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    step_door.snapshot(job=packet, width=PICTURE_PX[0], height=PICTURE_PX[1])
    missing = [str(path) for path in out.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"the snapshot wrote no picture at {', '.join(missing)}")
    return out


# --- layout ------------------------------------------------------------------

Draw = Callable[[object], None]


class _Measure:
    def __init__(self) -> None:
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextToPath

        self._path = TextToPath()
        self._props = {weight: FontProperties(family="DejaVu Sans", weight=weight) for weight in ("normal", "bold")}

    def width(self, text: str, size: float, weight: str = "normal") -> float:
        if not text:
            return 0.0
        props = self._props[weight].copy()
        props.set_size(size)
        w, _h, _d = self._path.get_text_width_height_descent(text, props, ismath=False)
        return w * PT

    def wrap(self, text: str, size: float, width: float, weight: str = "normal") -> list[str]:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split(" "):
                candidate = f"{line} {word}" if line else word
                if not line or self.width(candidate, size, weight) <= width:
                    line = candidate
                    continue
                lines.append(line)
                line = word
            while self.width(line, size, weight) > width and len(line) > 1:  # one word wider than the column
                cut = max(1, int(len(line) * width / self.width(line, size, weight)))
                lines.append(line[:cut])
                line = line[cut:]
            lines.append(line)
        return lines


class _Flow:
    """Pages of draw commands, filled top-down; a block that does not fit starts a page."""

    def __init__(self, wi, open_count: int) -> None:
        self.wi = wi
        self.w, self.h = PAGE_MM[wi.size]
        self.measure = _Measure()
        self.open_count = open_count
        self.pages: list[list[Draw]] = []
        self.continued = ""
        self.new_page()

    @property
    def inner(self) -> float:
        return self.w - 2 * MARGIN

    def new_page(self) -> None:
        self.pages.append([])
        self.y = self.h - MARGIN - 17.0  # below the header band
        if self.wi.status == "draft":
            self.y -= 7.0
        if self.continued:
            self.text(f"{self.continued} (CONTINUED)", HEAD, weight="bold")
            self.y -= 2.0

    def room(self, height: float) -> None:
        if self.y - height < MARGIN + 8.0:
            self.new_page()
            if self.y - height < MARGIN + 8.0:
                raise ValueError(
                    f"{self.continued or 'the cover'}: one block of text is taller than a page "
                    f"({height:.0f} mm); split it into shorter instructions"
                )

    def add(self, draw: Draw) -> None:
        self.pages[-1].append(draw)

    def text(self, value: str, size: float = BODY, *, x: float | None = None, width: float | None = None,
             weight: str = "normal", color: str = "black") -> None:
        x = MARGIN if x is None else x
        lines = self.measure.wrap(value, size, width or self.inner, weight)
        step = size * PT * 1.35
        self.room(step * len(lines))
        for line in lines:
            y = self.y - size * PT
            self.add(lambda ax, line=line, y=y: ax.text(x, y, line, fontsize=size, weight=weight, color=color,
                                                         va="baseline", ha="left"))
            self.y -= step

    def rule(self, *, gap: float = 2.0, weight: float = 0.4, color: str = "#888888") -> None:
        y = self.y - gap / 2
        self.add(lambda ax: ax.plot([MARGIN, self.w - MARGIN], [y, y], lw=weight, color=color))
        self.y -= gap

    def row(self, cells: list[tuple[str | None, float, float, str]], *, pad: float = 1.6) -> None:
        """One table row: (text or None = NOT STATED, x, width, weight) per cell."""
        size = BODY
        wrapped = []
        for value, _x, width, weight in cells:
            wrapped.append(["NOT STATED"] if value is None else self.measure.wrap(value, size, width - 2, weight))
        step = size * PT * 1.35
        height = step * max(len(lines) for lines in wrapped) + pad
        self.room(height)
        top = self.y
        for (value, x, width, weight), lines in zip(cells, wrapped):
            if value is None:
                box_w = self.measure.width("NOT STATED", SMALL, "bold") + 5
                self.add(lambda ax, x=x, top=top, box_w=box_w: _not_stated(ax, x, top - step - 0.6, box_w))
                continue
            for i, line in enumerate(lines):
                y = top - size * PT - i * step - pad / 2
                self.add(lambda ax, line=line, x=x, y=y, weight=weight: ax.text(
                    x, y, line, fontsize=size, weight=weight, va="baseline", ha="left"))
        self.y -= height
        y = self.y
        self.add(lambda ax: ax.plot([MARGIN, self.w - MARGIN], [y, y], lw=0.2, color="#bbbbbb"))

    def blanks(self, captions: tuple[str, ...], *, per_row: int = 3) -> None:
        """Fill-ins the floor writes: a caption over a line, ``per_row`` to a row."""
        if not captions:
            return
        width = self.inner / per_row
        for start in range(0, len(captions), per_row):
            self.room(9.0)
            top = self.y
            for i, caption in enumerate(captions[start:start + per_row]):
                x = MARGIN + i * width
                self.add(lambda ax, x=x, top=top, caption=caption: _blank(ax, x, top, width - 4, caption))
            self.y -= 9.0

    def image(self, path: Path, legend: tuple[tuple[str, str], ...]) -> None:
        import matplotlib.image as mpimg

        pixels = mpimg.imread(str(path))
        if pixels.shape[-1] == 4:  # over white: a page has no use for an alpha mask beside each picture
            alpha = pixels[..., 3:4]
            pixels = pixels[..., :3] * alpha + (1.0 - alpha)
        height = self.inner * PICTURE_PX[1] / PICTURE_PX[0]
        self.room(height + 6)
        top = self.y
        self.add(lambda ax: ax.imshow(pixels, extent=(MARGIN, self.w - MARGIN, top - height, top),
                                      interpolation="antialiased", zorder=1))
        self.add(lambda ax: ax.add_patch(_rect(MARGIN, top - height, self.inner, height, lw=0.3, edge="#bbbbbb")))
        self.y -= height + 1.0
        x = MARGIN
        for color, label in legend:
            face = "white" if color is None else color
            self.add(lambda ax, x=x, y=self.y, face=face: ax.add_patch(
                _rect(x, y - 3.0, 3.0, 2.4, lw=0.4, edge="black", face=face)))
            self.add(lambda ax, x=x, y=self.y, label=label: ax.text(
                x + 4.0, y - 2.6, label, fontsize=SMALL, va="baseline", ha="left", color="#444444"))
            x += 6.0 + self.measure.width(label, SMALL)
        self.y -= 5.0


def _rect(x, y, w, h, *, lw, edge, face="none"):
    from matplotlib.patches import Rectangle

    return Rectangle((x, y), w, h, linewidth=lw, edgecolor=edge, facecolor=face, zorder=2)


def _not_stated(ax, x, y, width) -> None:
    from matplotlib.patches import Rectangle

    ax.add_patch(Rectangle((x, y - 1.2), width, SMALL * PT + 2.6, linewidth=0.8, edgecolor="black",
                           facecolor="white", hatch="////", zorder=2))
    ax.text(x + 2.5, y, "NOT STATED", fontsize=SMALL, weight="bold", va="baseline", ha="left", zorder=3,
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.6})


def _blank(ax, x, top, width, caption) -> None:
    ax.text(x, top - SMALL * PT, caption.upper(), fontsize=SMALL - 0.5, color="#555555", va="baseline", ha="left")
    ax.plot([x, x + width], [top - 7.0, top - 7.0], lw=0.5, color="black")


def _fit(measure: "_Measure", text: str, size: float, width: float, *, smallest: float = 7.0) -> tuple[str, float]:
    """``text`` at the largest size down to ``smallest`` that fits ``width``; past
    that, cut with an ellipsis -- the full title is on the cover, wrapped."""
    while size > smallest and measure.width(text, size, "bold") > width:
        size -= 0.5
    while measure.width(text, size, "bold") > width and len(text) > 1:
        text = text[:-2].rstrip() + "\u2026"
    return text, size


def _header(ax, measure: "_Measure", wi, w, h, page: int, count: int, open_count: int) -> None:
    top = h - MARGIN
    ax.add_patch(_rect(MARGIN, top - 15.0, w - 2 * MARGIN, 15.0, lw=0.6, edge="black"))
    number = f"{wi.number}  REV {wi.revision}"
    room = w - 2 * MARGIN - 10.0 - measure.width(number, HEAD, "bold")
    title, size = _fit(measure, wi.title, HEAD + 1, room)
    ax.text(MARGIN + 2.5, top - 6.5, title, fontsize=size, weight="bold", va="baseline")
    ax.text(w - MARGIN - 2.5, top - 6.5, number, fontsize=HEAD, weight="bold", va="baseline", ha="right")
    detail = "WORK INSTRUCTION"
    if wi.part_number:
        detail += f"   ASSEMBLY P/N {wi.part_number}"
    if wi.drawing is not None:
        detail += f"   DRAWING {wi.drawing.name}"
    ax.text(MARGIN + 2.5, top - 12.0, detail, fontsize=SMALL, va="baseline", color="#333333")
    ax.text(w - MARGIN - 2.5, top - 12.0, f"PAGE {page} OF {count}", fontsize=SMALL, va="baseline", ha="right")
    if wi.status == "draft":
        ax.add_patch(_rect(MARGIN, top - 22.0, w - 2 * MARGIN, 5.5, lw=0.8, edge="black", face="#eeeeee"))
        items = f"{open_count} OPEN ITEM{'S' if open_count != 1 else ''}" if open_count else "NO OPEN ITEMS"
        ax.text(w / 2, top - 20.4, f"DRAFT — NOT FOR PRODUCTION — {items}", fontsize=BODY,
                weight="bold", va="baseline", ha="center")
    ax.text(MARGIN, MARGIN - 4.0, f"Generated from {wi.step_path.name}", fontsize=SMALL - 1, color="#666666",
            va="baseline")


def _cover(flow: _Flow, wi, open_items: list[str]) -> None:
    flow.text("WORK INSTRUCTION", SMALL, weight="bold", color="#555555")
    flow.text(wi.title, TITLE, weight="bold")
    flow.y -= 2.0
    caption_w, x2 = 38.0, MARGIN + 38.0
    info = [("Number", f"{wi.number} Rev {wi.revision}"), ("Assembly", wi.step_path.name)]
    if wi.part_number:
        info.append(("Part number", wi.part_number))
    if wi.drawing is not None:
        info.append(("Drawing", wi.drawing.name))
    info.append(("Status", wi.status.upper()))
    for caption, value in info:
        flow.row([(caption, MARGIN, caption_w, "bold"), (value, x2, flow.inner - caption_w, "normal")])
    flow.blanks(("Prepared by" + (f": {wi.author}" if wi.author else ""), "Approved by", "Date"))

    _section(flow, "DOCUMENTS")
    documents = wi.documents()
    if not documents:
        flow.text("No process specification or drawing is cited.", BODY, color="#555555")
    for name, title in documents:
        flow.row([(name, MARGIN, 50.0, "bold"), (title or "", MARGIN + 50.0, flow.inner - 50.0, "normal")])

    _section(flow, "PARTS")
    groups: dict[str, list] = {}
    for leaf in wi.leaves():
        groups.setdefault(leaf.label or "(unnamed)", []).append(leaf)
    widths = (60.0, 14.0, 22.0)
    flow.row([("PART", MARGIN, widths[0], "bold"), ("QTY", MARGIN + widths[0], widths[1], "bold"),
              ("STEP", MARGIN + sum(widths[:2]), widths[2], "bold"),
              ("OCCURRENCES", MARGIN + sum(widths), flow.inner - sum(widths), "bold")])
    for label, leaves in groups.items():
        steps = sorted({wi._installed[leaf.ref] for leaf in leaves if leaf.ref in wi._installed})
        flow.row([(label, MARGIN, widths[0], "normal"), (str(len(leaves)), MARGIN + widths[0], widths[1], "normal"),
                  (", ".join(map(str, steps)) or None, MARGIN + sum(widths[:2]), widths[2], "normal"),
                  (" ".join(leaf.ref for leaf in leaves), MARGIN + sum(widths), flow.inner - sum(widths), "normal")])

    if wi.materials:
        _section(flow, "MATERIALS")
        for record in wi.materials:
            flow.row([(record.name, MARGIN, 60.0, "bold"), (type(record).__name__.lower(), MARGIN + 60.0, 24.0, "normal"),
                      (record.per.cite(), MARGIN + 84.0, flow.inner - 84.0, "normal")])
            flow.blanks(("Lot / batch", "Expiry"))

    if wi.status == "draft":
        _section(flow, "OPEN ITEMS")
        if not open_items:
            flow.text("None: every value is stated and every part is installed.", BODY)
        for item in open_items:
            flow.text(f"• {item}", BODY)


def _section(flow: _Flow, title: str) -> None:
    flow.room(16.0)
    flow.y -= 3.0
    flow.text(title, BODY + 0.5, weight="bold")
    flow.rule(gap=1.5, weight=0.6, color="black")


def _step(flow: _Flow, wi, step, picture: Path | None) -> None:
    flow.continued = ""
    flow.new_page()
    flow.continued = f"STEP {step.number}"
    flow.text(f"STEP {step.number}", SMALL, weight="bold", color="#555555")
    flow.text(step.title, HEAD + 2, weight="bold")
    if step.hold:
        flow.text("INSPECTION HOLD POINT: do not proceed until stamped.", BODY, weight="bold")
    flow.y -= 1.5
    if picture is not None:
        earlier = any(s.install for s in wi.steps[:step.number - 1])
        surfaces = any(op.surfaces for op in step.ops)
        legend = tuple(entry for entry, shown in (((NEW_PART, "THIS STEP"), bool(step.install)),
                                                  ((None, "INSTALLED EARLIER (OUTLINE)"), earlier),
                                                  ((SURFACE, "SURFACE"), surfaces)) if shown)
        flow.image(picture, legend)
    if step.install:
        names = {leaf.ref: leaf.label or "(unnamed)" for leaf in wi.leaves()}
        flow.row([("Install", MARGIN, 26.0, "bold"),
                  (", ".join(f"{names[ref]} ({ref})" for ref in step.install), MARGIN + 26.0, flow.inner - 26.0,
                   "normal")])
    caption_w, source_w = 26.0, 58.0
    value_x, value_w = MARGIN + caption_w, flow.inner - caption_w - source_w
    for op in step.ops:
        for line in op.lines:
            if op.kind == "instruct":
                flow.row([(line.value, MARGIN, flow.inner, "normal")])
                continue
            cited = "per " + line.source.cite() if line.source else (None if line.cite else "")
            flow.row([(line.caption, MARGIN, caption_w, "bold"), (line.value, value_x, value_w, "normal"),
                      (cited, value_x + value_w, source_w, "normal")])
        flow.blanks(_records(op.kind))
    flow.y -= 3.0
    flow.blanks(("Technician", "Date") + (("Inspector stamp", "Date") if step.hold else ()), per_row=4)


def _records(kind: str) -> tuple[str, ...]:
    from cadgen.work_instruction import RECORDS

    return RECORDS.get(kind, ())


# --- the PDF -----------------------------------------------------------------


def layout(wi, open_items: list[str], pictures: dict[int, Path]) -> _Flow:
    """The pages as draw commands: the cover, then each step from a new page."""
    flow = _Flow(wi, len(open_items))
    _cover(flow, wi, open_items)
    for step in wi.steps:
        _step(flow, wi, step, pictures.get(step.number))
    return flow


def draw_page(ax, flow: _Flow, index: int, open_count: int) -> None:
    """Page ``index`` (from 1), its header first, onto a matplotlib axes in millimetres."""
    _header(ax, flow.measure, flow.wi, flow.w, flow.h, index, len(flow.pages), open_count)
    for draw in flow.pages[index - 1]:
        draw(ax)


def write_pdf(wi, path: Path, *, open_items: list[str]) -> int:
    """Lay out and write the instruction; returns the page count."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError as exc:
        raise RuntimeError(
            f"@work_instruction writes a PDF and its renderer is missing: {exc}. "
            "Install cadgen's dependencies (pip install matplotlib pillow)."
        ) from exc
    from cadgen._internal.atomic_replace import temp_suffix

    picture_plan(wi)  # refuses a mark on a part not yet installed, before any render
    with tempfile.TemporaryDirectory(prefix="cadgen-wi-") as folder:
        pictures = render_pictures(wi, Path(folder)) if wi.pictures else {}
        flow = layout(wi, open_items, pictures)

        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}{temp_suffix()}")
        count = len(flow.pages)
        try:
            with PdfPages(partial, metadata={"CreationDate": None}) as pdf:
                for index in range(1, count + 1):
                    fig = plt.figure(figsize=(flow.w / 25.4, flow.h / 25.4))
                    ax = fig.add_axes([0, 0, 1, 1])
                    ax.set_xlim(0, flow.w)
                    ax.set_ylim(0, flow.h)
                    ax.set_aspect("equal")
                    ax.axis("off")
                    draw_page(ax, flow, index, len(open_items))
                    ax.set_xlim(0, flow.w)
                    ax.set_ylim(0, flow.h)
                    pdf.savefig(fig)
                    plt.close(fig)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return count

