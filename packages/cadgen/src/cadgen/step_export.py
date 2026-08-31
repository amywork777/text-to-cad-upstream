from __future__ import annotations

import os
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from cadgen._internal.step_scene import LoadedStepScene, load_step_scene_from_xcaf_doc, step_file_hash


def _collect_assembly_mates(shape: Any) -> list[dict[str, Any]]:
    mates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        raw_mates = getattr(node, "assembly_mates", None)
        if isinstance(raw_mates, list):
            for raw_mate in raw_mates:
                if not isinstance(raw_mate, dict):
                    continue
                key = repr(raw_mate)
                if key in seen:
                    continue
                seen.add(key)
                mate = dict(raw_mate)
                mate_id = f"m{len(mates) + 1}"
                source_label = str(
                    mate.get("sourceLabel") or
                    mate.get("name") or
                    mate.get("label") or
                    mate.get("id") or
                    ""
                ).strip()
                mate["id"] = mate_id
                mate["label"] = mate_id
                if source_label and source_label != mate_id:
                    mate["sourceLabel"] = source_label
                mates.append(mate)
        for child in list(getattr(node, "children", []) or []):
            visit(child)

    visit(shape)
    return mates


def _attach_assembly_mates(scene: LoadedStepScene, shape: Any) -> LoadedStepScene:
    assembly_mates = _collect_assembly_mates(shape)
    if assembly_mates:
        scene.assembly_mates = assembly_mates
    return scene


def create_bin_xcaf_doc() -> Any:
    from OCP.BinXCAFDrivers import BinXCAFDrivers
    from build123d.exporters3d import (
        TCollection_ExtendedString,
        TDocStd_Document,
        UNITS_PER_METER,
        Unit,
        XCAFApp_Application,
        XCAFDoc_DocumentTool,
    )

    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    application = XCAFApp_Application.GetApplication_s()
    BinXCAFDrivers.DefineFormat_s(application)
    application.NewDocument(TCollection_ExtendedString("BinXCAF"), doc)
    application.InitDocument(doc)
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 1 / UNITS_PER_METER[Unit.MM])
    return doc


def quantity_color_rgba_from_color(color: object) -> object | None:
    """Return a Quantity_ColorRGBA with explicit linear RGB semantics.

    build123d.Color exposes its values through Quantity_ColorRGBA.GetRGB().
    Different OCP versions can serialize that wrapped color with different
    implicit color-space assumptions, so normalize through Quantity_TOC_RGB
    before writing XCAF labels.
    """
    if color is None:
        return None

    if isinstance(color, tuple):
        values = tuple(max(0.0, min(1.0, float(component))) for component in color)
        if len(values) == 3:
            rgba = (values[0], values[1], values[2], 1.0)
        elif len(values) >= 4:
            rgba = (values[0], values[1], values[2], values[3])
        else:
            return None
    else:
        wrapped = getattr(color, "wrapped", None)
        if wrapped is None:
            return None
        try:
            rgb = wrapped.GetRGB()
            rgba = (
                max(0.0, min(1.0, float(rgb.Red()))),
                max(0.0, min(1.0, float(rgb.Green()))),
                max(0.0, min(1.0, float(rgb.Blue()))),
                max(0.0, min(1.0, float(wrapped.Alpha()))),
            )
        except Exception:  # noqa: BLE001 - OCP Quantity color reads can raise C++ exceptions; fall back to the wrapped color
            return wrapped

    from OCP.Quantity import Quantity_Color, Quantity_ColorRGBA, Quantity_TOC_RGB

    rgb_color = Quantity_Color(rgba[0], rgba[1], rgba[2], Quantity_TOC_RGB)
    wrapped_rgba = Quantity_ColorRGBA(rgb_color)
    wrapped_rgba.SetAlpha(rgba[3])
    return wrapped_rgba


def _create_bin_xcaf_doc(to_export: Any) -> Any:
    from OCP.TopLoc import TopLoc_Location
    from build123d.exporters3d import (
        Compound,
        Curve,
        Part,
        PreOrderIter,
        Sketch,
        TCollection_ExtendedString,
        TDataStd_Name,
        TopExp_Explorer,
        XCAFDoc_ColorType,
        XCAFDoc_DocumentTool,
        ta,
    )

    doc = create_bin_xcaf_doc()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    is_assembly = isinstance(to_export, Compound) and len(to_export.children) > 0
    shape_definitions: dict[int, object] = {}

    def set_label_name(label: object, name: str | None) -> None:
        if name and not label.IsNull():
            TDataStd_Name.Set_s(label, TCollection_ExtendedString(str(name)))

    def set_label_color(label: object, color: object | None) -> None:
        if color is None or label.IsNull():
            return
        wrapped = quantity_color_rgba_from_color(color)
        if wrapped is None:
            return
        color_tool.SetColor(
            label,
            wrapped,
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        )

    def shape_location(shape: object) -> object:
        wrapped = getattr(shape, "wrapped", None)
        if wrapped is None:
            return TopLoc_Location()
        location = getattr(wrapped, "Location", None)
        if not callable(location):
            return TopLoc_Location()
        try:
            return location()
        except Exception:  # noqa: BLE001 - OCP Location() can raise; degrade to the identity location
            return TopLoc_Location()

    def shape_without_location(shape: object) -> object:
        wrapped = getattr(shape, "wrapped", None)
        if wrapped is None:
            return shape
        located = getattr(wrapped, "Located", None)
        if not callable(located):
            return wrapped
        try:
            return located(TopLoc_Location())
        except Exception:  # noqa: BLE001 - OCP Located() can raise on unusual shapes; keep the unlocated shape
            return wrapped

    def shape_definition_for_tree(shape: object) -> object:
        key = id(shape)
        cached = shape_definitions.get(key)
        if cached is not None:
            return cached

        children = list(getattr(shape, "children", []) or [])
        if children:
            definition_label = shape_tool.NewShape()
            shape_definitions[key] = definition_label
            set_label_name(definition_label, getattr(shape, "label", None))
            set_label_color(definition_label, getattr(shape, "color", None))
            for child in children:
                child_definition = shape_definition_for_tree(child)
                child_component = shape_tool.AddComponent(
                    definition_label,
                    child_definition,
                    shape_location(child),
                )
                set_label_name(child_component, getattr(child, "label", None))
                set_label_color(child_component, getattr(child, "color", None))
            return definition_label

        definition_label = shape_tool.AddShape(shape_without_location(shape), False)
        shape_definitions[key] = definition_label
        set_label_name(definition_label, getattr(shape, "label", None))
        set_label_color(definition_label, getattr(shape, "color", None))
        return definition_label

    if is_assembly:
        shape_definition_for_tree(to_export)
        shape_tool.UpdateAssemblies()
        return doc

    shape_tool.AddShape(to_export.wrapped, is_assembly)

    for node in PreOrderIter(to_export):
        if not node.label and node.color is None:
            continue

        node_label = shape_tool.FindShape(node.wrapped, findInstance=False)
        sub_node_labels = []
        if node.color is not None and isinstance(node, Compound) and not node.children:
            sub_nodes = []
            if isinstance(node, Part):
                explorer = TopExp_Explorer(node.wrapped, ta.TopAbs_SOLID)
            elif isinstance(node, Sketch):
                explorer = TopExp_Explorer(node.wrapped, ta.TopAbs_FACE)
            elif isinstance(node, Curve):
                explorer = TopExp_Explorer(node.wrapped, ta.TopAbs_EDGE)
            else:
                # A bare `Compound` leaf (a boolean/chamfer chain that came
                # back as plain Compound rather than Part/Sketch/Curve) still
                # holds valid colored geometry. Warning and skipping here
                # silently exported it uncolored — the per-component doc path
                # ships each leaf alone, so the model rendered washed-out.
                # Color whatever the compound actually contains, most solid
                # content first.
                explorer = TopExp_Explorer(node.wrapped, ta.TopAbs_SOLID)
                if not explorer.More():
                    explorer = TopExp_Explorer(node.wrapped, ta.TopAbs_FACE)
                if not explorer.More():
                    explorer = TopExp_Explorer(node.wrapped, ta.TopAbs_EDGE)

            while explorer.More():
                sub_nodes.append(explorer.Current())
                explorer.Next()

            sub_node_labels = [
                shape_tool.FindShape(sub_node, findInstance=False)
                for sub_node in sub_nodes
            ]
        set_label_name(node_label, node.label)

        if node.color is not None:
            for label in [node_label] + sub_node_labels:
                set_label_color(label, node.color)

    shape_tool.UpdateAssemblies()
    return doc


def export_xcaf_doc_step_scene(
    doc: Any,
    output_path: Path,
    *,
    label: str | None = None,
    originating_system: str = "cadgen",
    logger: object | None = None,
) -> LoadedStepScene:
    step_hash = write_xcaf_doc_step_file(
        doc,
        output_path,
        label=label,
        originating_system=originating_system,
        logger=logger,
    )
    with (logger.timed(f"load scene from XCAF {output_path.name}") if logger is not None else nullcontext()):
        return load_step_scene_from_xcaf_doc(
            output_path,
            doc,
            step_hash=step_hash,
        )


def _renumber_nauo_ids(model: Any) -> None:
    from OCP.StepRepr import StepRepr_NextAssemblyUsageOccurrence
    from OCP.TCollection import TCollection_HAsciiString

    # SelectType filters C++-side; a Python isinstance scan over every entity
    # costs ~1s on multi-million-entity models.
    iterator = model.Entities()
    iterator.SelectType(StepRepr_NextAssemblyUsageOccurrence.get_type_descriptor_s(), True)
    count = 0
    iterator.Start()
    while iterator.More():
        count += 1
        iterator.Value().SetId(TCollection_HAsciiString(str(count)))
        iterator.Next()


_MDGPR_TYPE = "StepVisual_MechanicalDesignGeometricPresentationRepresentation"

# The complete entity family OCCT's writeColors() appends per styled product
# (STEPCAFControl_Writer.cxx, MakeSTEPStyles + "register all MDGPRs in model").
# _style_tail_plan only orders a tail made entirely of these;
# an unexpected type in the tail means the writer changed shape, and the
# canonicalization steps aside rather than guess.
_STYLE_TAIL_FAMILY = frozenset({
    _MDGPR_TYPE,
    "StepVisual_StyledItem",
    "StepVisual_OverRidingStyledItem",
    "StepVisual_PresentationStyleAssignment",
    "StepVisual_PresentationStyleByContext",
    "StepVisual_SurfaceStyleUsage",
    "StepVisual_SurfaceSideStyle",
    "StepVisual_SurfaceStyleFillArea",
    # Emitted only for a part whose colour carries alpha: the transparency rides
    # a rendering entity hanging off the same SurfaceSideStyle as the fill area.
    # Without these two the tail-family check below rejected every model with a
    # single transparent part and left it writing address-ordered bytes.
    "StepVisual_SurfaceStyleRendering",
    "StepVisual_SurfaceStyleRenderingWithProperties",
    "StepVisual_SurfaceStyleTransparent",
    "StepVisual_FillAreaStyle",
    "StepVisual_FillAreaStyleColour",
    "StepVisual_ColourRgb",
    "StepVisual_Colour",
    "StepVisual_PreDefinedColour",
    "StepVisual_DraughtingPreDefinedColour",
    "StepVisual_CurveStyle",
    "StepVisual_DraughtingPreDefinedCurveFont",
})


def _style_entity_children(ent: Any) -> list:
    """One style-tail entity's referenced entities, in FIELD order — the same
    order AddWithRefs traverses, so a canonical DFS reproduces each closure's
    internal layout exactly."""
    name = ent.DynamicType().Name()
    out: list = []

    def add(value: object) -> None:
        if value is not None:
            out.append(value)

    def add_select(select: object) -> None:
        value = getattr(select, "Value", None)
        add(value() if callable(value) else select)

    def add_array(array: object) -> None:
        if array is not None:
            for index in range(1, array.Length() + 1):
                add_select(array.Value(index))

    if name == _MDGPR_TYPE:
        add_array(ent.Items())
    elif name in ("StepVisual_StyledItem", "StepVisual_OverRidingStyledItem"):
        add(ent.Item())
        add_array(ent.Styles())
        if name == "StepVisual_OverRidingStyledItem":
            add(ent.OverRiddenStyle())
    elif name in ("StepVisual_PresentationStyleAssignment", "StepVisual_PresentationStyleByContext"):
        add_array(ent.Styles())
        if name == "StepVisual_PresentationStyleByContext":
            add_select(ent.StyleContext())
    elif name == "StepVisual_SurfaceStyleUsage":
        add(ent.Style())
    elif name == "StepVisual_SurfaceSideStyle":
        add_array(ent.Styles())
    elif name == "StepVisual_SurfaceStyleFillArea":
        add(ent.FillArea())
    elif name == "StepVisual_FillAreaStyle":
        add_array(ent.FillStyles())
    elif name == "StepVisual_FillAreaStyleColour":
        add(ent.FillColour())
    elif name in (
        "StepVisual_SurfaceStyleRendering",
        "StepVisual_SurfaceStyleRenderingWithProperties",
    ):
        # SURFACE_STYLE_RENDERING[_WITH_PROPERTIES](rendering_method, surface_colour
        # [, properties]): the method is an enum, not an entity, so the DFS starts at
        # the colour. `properties` is a select array whose members are the
        # SurfaceStyleTransparent leaves.
        add(ent.SurfaceColour())
        if name == "StepVisual_SurfaceStyleRenderingWithProperties":
            add_array(ent.Properties())
    # Colours, transparency values, and predefined fonts are leaves.
    return out


def _style_tail_plan(model: Any) -> tuple[int, int, list[int]] | None:
    """The canonical order for the style section, as entity NUMBERS.

    OCCT registers each styled product's presentation graph by iterating an
    ADDRESS-hashed shape map (STEPCAFControl_Writer::transfer's myMapCompMDGPR,
    still address-hashed on master), so with two or more styled products the
    MDGPR closures — and every entity number after them — land in heap-address
    order: byte-different files for identical models, varying per process and
    even per call. Everything before the style tail is deterministic transfer
    order (see _renumber_nauo_ids, which leans on the same property).

    The canonical order: MDGPR blocks sorted by the styled targets they
    reference (head entity numbers, which ARE stable), each closure laid out in
    field-order DFS. Entities shared between closures (deduplicated colours)
    land with the first canonical owner. Anything unexpected in the tail
    returns None — worst case is the old nondeterminism, never a corrupt file.

    Returns ``(tail_start, total, old_numbers)`` where ``old_numbers[i]`` is the
    entity that must end up numbered ``tail_start + i``. This function only
    READS the model; the two appliers below differ in where they put the
    permutation, not in what it is.
    """
    from OCP.StepVisual import (
        StepVisual_MechanicalDesignGeometricPresentationRepresentation as _MDGPR,
    )

    # Cheap C++-side count first: parts and single-product assemblies have at
    # most one MDGPR, one closure, nothing to permute — skip the Python scan.
    iterator = model.Entities()
    iterator.SelectType(_MDGPR.get_type_descriptor_s(), True)
    mdgpr_count = 0
    iterator.Start()
    while iterator.More():
        mdgpr_count += 1
        iterator.Next()
    if mdgpr_count <= 1:
        return None

    total = model.NbEntities()
    # OCP's model.Number() binding returns 0, so numbers come from this scan;
    # Entity(i) returns an identity-stable wrapper, so id() keys are sound
    # while `entities` holds the references.
    entities = [None] + [model.Entity(index) for index in range(1, total + 1)]
    type_names = [None] + [ent.DynamicType().Name() for ent in entities[1:]]
    mdgpr_nums = [i for i in range(1, total + 1) if type_names[i] == _MDGPR_TYPE]
    tail_start = mdgpr_nums[0]
    if any(type_names[i] not in _STYLE_TAIL_FAMILY for i in range(tail_start, total + 1)):
        return None
    number_of = {id(ent): index for index, ent in enumerate(entities[1:], start=1)}
    tail_ids = {id(entities[i]) for i in range(tail_start, total + 1)}

    def block_key(mdgpr_num: int) -> tuple:
        targets = []
        for item in _style_entity_children(entities[mdgpr_num]):
            if item.DynamicType().Name() in ("StepVisual_StyledItem", "StepVisual_OverRidingStyledItem"):
                target_num = number_of.get(id(item.Item()))
                if target_num is not None and target_num < tail_start:
                    targets.append(target_num)
        return (tuple(sorted(targets)), mdgpr_num)

    desired: list = []
    seen: set[int] = set()

    def visit(ent: Any) -> None:
        if id(ent) not in tail_ids or id(ent) in seen:
            return
        seen.add(id(ent))
        desired.append(ent)
        for child in _style_entity_children(ent):
            visit(child)

    for mdgpr_num in sorted(mdgpr_nums, key=block_key):
        visit(entities[mdgpr_num])
    if len(desired) != total - tail_start + 1:
        return None
    return tail_start, total, [number_of[id(ent)] for ent in desired]


def _apply_style_tail_plan_in_model(model: Any, tail_start: int, old_numbers: list[int]) -> None:
    """Permute the model itself, one ``ChangeOrder`` per tail entity.

    Exact, and quadratic: each call renumbers a model that holds ~10^5-10^6
    entities, so juno's ~3400-entity tail costs ~110 s. It survives only as the
    backstop for the one case the text applier below refuses (a tail whose
    entity numbers do not all have the same digit width); the byte-identity
    test pins the two appliers to the same output.
    """
    total = tail_start + len(old_numbers) - 1
    order = list(range(tail_start, total + 1))
    for offset, old_number in enumerate(old_numbers):
        current = tail_start + order.index(old_number)
        target = tail_start + offset
        if current != target:
            model.ChangeOrder(current, target)
            order.remove(old_number)
            order.insert(offset, old_number)


# A STEP record header: `#123 = TYPE(...)`, always at the start of a line. A
# wrapped continuation line can also begin with `#`, but only a header carries
# the ` = `, so this cannot mistake one for the other.
_STEP_RECORD_START = re.compile(r"(?m)^#(\d+) = ")
# A quoted STEP string OR an entity reference. The string alternative comes
# first and consumes the whole literal (`''` is an escaped quote), so a `#` that
# happens to sit inside a part name is never rewritten as a reference.
_STEP_STRING_OR_REF = re.compile(r"'(?:[^']|'')*'|#(\d+)")


def _apply_style_tail_plan_in_text(
    text: str, tail_start: int, old_numbers: list[int]
) -> str | None:
    """The same permutation, applied to the WRITTEN file instead of the model.

    Two linear passes over the text: renumber every reference through the
    old->new map (the regex skips string literals), then reorder the tail
    records, which are a contiguous suffix of the DATA section. Returns None if
    the text does not have the shape this expects.

    This is byte-identical to the in-model applier only because the caller
    guarantees every rewritten number keeps its digit width: OCCT wraps long
    records at a fixed column, so a number that grew a digit would shift the
    wrapping and produce a differently-formatted (though semantically equal)
    file. Same width in, same bytes out.
    """
    new_of = {old: tail_start + offset for offset, old in enumerate(old_numbers)}
    if all(old == new for old, new in new_of.items()):
        return text

    def renumber(match: "re.Match[str]") -> str:
        digits = match.group(1)
        if digits is None:  # a string literal — leave it exactly as written
            return match.group(0)
        number = int(digits)
        replacement = new_of.get(number)
        return match.group(0) if replacement is None else f"#{replacement}"

    renumbered = _STEP_STRING_OR_REF.sub(renumber, text)

    # Record starts, so the tail records can be sorted into their new order.
    # After the substitution above each header carries its NEW number.
    headers = list(_STEP_RECORD_START.finditer(renumbered))
    if not headers:
        return None
    first_tail = next(
        (i for i, m in enumerate(headers) if int(m.group(1)) >= tail_start), None
    )
    if first_tail is None or len(headers) - first_tail != len(old_numbers):
        return None
    region_start = headers[first_tail].start()
    end_marker = renumbered.find("\nENDSEC;", region_start)
    if end_marker < 0:
        return None
    region_end = end_marker + 1  # the last record keeps its trailing newline
    bounds = [m.start() for m in headers[first_tail:]] + [region_end]
    records = [
        (int(headers[first_tail + i].group(1)), renumbered[bounds[i]:bounds[i + 1]])
        for i in range(len(bounds) - 1)
    ]
    records.sort(key=lambda record: record[0])
    return (
        renumbered[:region_start]
        + "".join(body for _number, body in records)
        + renumbered[region_end:]
    )


def write_xcaf_doc_step_file(
    doc: Any,
    output_path: Path,
    *,
    label: str | None = None,
    originating_system: str = "cadgen",
    logger: object | None = None,
) -> str:
    from build123d.exporters3d import (
        APIHeaderSection_MakeHeader,
        IFSelect_ReturnStatus,
        IGESControl_Controller,
        Interface_Static,
        Message,
        Message_Gravity,
        PrecisionMode,
        STEPCAFControl_Controller,
        STEPCAFControl_Writer,
        STEPControl_Controller,
        STEPControl_StepModelType,
        TCollection_HAsciiString,
        XSControl_WorkSession,
    )

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    messenger = Message.DefaultMessenger_s()
    for printer in messenger.Printers():
        printer.SetTraceLevel(Message_Gravity(Message_Gravity.Message_Fail))

    session = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(session, False)
    writer.SetColorMode(True)
    writer.SetLayerMode(True)
    writer.SetNameMode(True)

    STEPCAFControl_Controller.Init_s()
    STEPControl_Controller.Init_s()
    IGESControl_Controller.Init_s()
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 1)
    Interface_Static.SetIVal_s("write.precision.mode", PrecisionMode.AVERAGE.value)
    with (logger.timed(f"transfer XCAF to STEP model {output_path.name}") if logger is not None else nullcontext()):
        writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)

    # NAUO instance ids come from a process-global OCCT counter, so a warm
    # process that has exported before writes different ids than a cold one
    # for the same model. Renumber them 1..N in model-entity order (which is
    # deterministic transfer order) so identical models write identical bytes.
    with (logger.timed("renumber NAUO ids") if logger is not None else nullcontext()):
        _renumber_nauo_ids(writer.Writer().Model())
    # Same contract, other direction: OCCT appends multi-product style graphs
    # in heap-address order. Reorder them into content order.
    #
    # The permutation is computed here, from the model, because model entity
    # numbers ARE the numbers Write() is about to emit. WHERE it gets applied is
    # a performance decision, not a correctness one:
    #
    #   - in the written TEXT (the normal path): two linear passes over the
    #     file, low single-digit seconds on the largest models we have;
    #   - in the MODEL, before writing: exact but quadratic — ~110 s on juno,
    #     because each ChangeOrder renumbers the whole model.
    #
    # The text applier is byte-identical to the model applier only while every
    # number it rewrites keeps its digit width (OCCT wraps records at a fixed
    # column, so a number that gained a digit would shift the wrapping). A tail
    # that straddles a power of ten is rare and cannot be made width-safe, so it
    # takes the slow path rather than writing differently-formatted bytes.
    with (logger.timed("plan style tail order") if logger is not None else nullcontext()):
        plan = _style_tail_plan(writer.Writer().Model())
    if plan is not None:
        tail_start, total, old_numbers = plan
        if (
            len(str(tail_start)) != len(str(total))
            or os.environ.get("CADGEN_STEP_STYLE_REORDER", "").strip() == "model"
        ):
            with (logger.timed("canonicalize style tail (in model)") if logger is not None else nullcontext()):
                _apply_style_tail_plan_in_model(
                    writer.Writer().Model(), tail_start, old_numbers
                )
            plan = None

    # The header must be edited AFTER Transfer: Transfer rebuilds the writer's
    # model, discarding anything set on the pre-transfer header.
    header = APIHeaderSection_MakeHeader(writer.Writer().Model())
    if label:
        header.SetName(TCollection_HAsciiString(label))
    header.SetOriginatingSystem(TCollection_HAsciiString(originating_system))
    # Byte-determinism: the only nondeterministic bytes in a written STEP are
    # FILE_NAME's wall-clock time_stamp. Exports are content-addressed
    # end-to-end (export records verify by sha256, identical models must
    # produce identical files), so the stamp is pinned. The real generation
    # time lives in the package descriptor, not the interchange file.
    header.SetTimeStamp(TCollection_HAsciiString("2000-01-01T00:00:00"))

    with (logger.timed(f"write STEP file {output_path.name}") if logger is not None else nullcontext()):
        if writer.Write(os.fspath(output_path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise RuntimeError(f"Failed to write STEP file: {output_path}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"STEP export did not create {output_path}")
    if plan is not None:
        with (logger.timed("canonicalize style tail (in text)") if logger is not None else nullcontext()):
            tail_start, _total, old_numbers = plan
            canonical = _apply_style_tail_plan_in_text(
                output_path.read_text(encoding="utf-8", errors="surrogateescape"),
                tail_start,
                old_numbers,
            )
            # A text shape this did not recognize leaves the file exactly as
            # OCCT wrote it: nondeterministically ordered, never corrupt.
            if canonical is not None:
                output_path.write_text(
                    canonical, encoding="utf-8", errors="surrogateescape"
                )
    return step_file_hash(output_path)


def export_build123d_step_scene(
    to_export: Any,
    output_path: Path,
) -> LoadedStepScene:
    doc = _create_bin_xcaf_doc(to_export)
    scene = export_xcaf_doc_step_scene(
        doc,
        output_path,
        label=getattr(to_export, "label", None),
    )
    return _attach_assembly_mates(scene, to_export)


def build_build123d_step_scene(
    to_export: Any,
    output_path: Path,
    *,
    source_kind: str = "step",
    source_hash: str | None = None,
) -> LoadedStepScene:
    doc = _create_bin_xcaf_doc(to_export)
    scene = load_step_scene_from_xcaf_doc(
        output_path,
        doc,
        source_kind=source_kind,
        source_hash=source_hash,
    )
    return _attach_assembly_mates(scene, to_export)


def export_build123d_step_file(
    to_export: Any,
    output_path: Path,
    *,
    logger: object | None = None,
) -> str:
    """Write a build123d shape to a text STEP file (no scene), returning its hash.

    The write-only counterpart to :func:`export_build123d_step_scene`, used by the
    on-demand ``--step`` export: the build already holds the in-memory scene/compound,
    so STEP export only needs to serialize the shape, not rebuild a scene."""
    with (logger.timed("build XCAF document") if logger is not None else nullcontext()):
        doc = _create_bin_xcaf_doc(to_export)
    return write_xcaf_doc_step_file(
        doc,
        output_path,
        label=getattr(to_export, "label", None),
        logger=logger,
    )
