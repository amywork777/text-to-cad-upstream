from __future__ import annotations

import os
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
# _canonicalize_presentation_styles only reorders a tail made entirely of these;
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
    # Colours and predefined fonts are leaves.
    return out


def _canonicalize_presentation_styles(model: Any) -> None:
    """Make the style section's entity order a function of model CONTENT.

    OCCT registers each styled product's presentation graph by iterating an
    ADDRESS-hashed shape map (STEPCAFControl_Writer::transfer's myMapCompMDGPR,
    still address-hashed on master), so with two or more styled products the
    MDGPR closures — and every entity number after them — land in heap-address
    order: byte-different files for identical models, varying per process and
    even per call. Everything before the style tail is deterministic transfer
    order (see _renumber_nauo_ids, which leans on the same property).

    Reorder the tail deterministically: MDGPR blocks sorted by the styled
    targets they reference (head entity numbers, which ARE stable), each
    closure laid out in field-order DFS. Entities shared between closures
    (deduplicated colours) land with the first canonical owner. Anything
    unexpected in the tail aborts untouched — worst case is the old
    nondeterminism, never a corrupt file.
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
        return

    total = model.NbEntities()
    # OCP's model.Number() binding returns 0, so numbers come from this scan;
    # Entity(i) returns an identity-stable wrapper, so id() keys are sound
    # while `entities` holds the references.
    entities = [None] + [model.Entity(index) for index in range(1, total + 1)]
    type_names = [None] + [ent.DynamicType().Name() for ent in entities[1:]]
    mdgpr_nums = [i for i in range(1, total + 1) if type_names[i] == _MDGPR_TYPE]
    tail_start = mdgpr_nums[0]
    if any(type_names[i] not in _STYLE_TAIL_FAMILY for i in range(tail_start, total + 1)):
        return
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
        return

    order = [id(entities[i]) for i in range(tail_start, total + 1)]
    for offset, ent in enumerate(desired):
        current = tail_start + order.index(id(ent))
        target = tail_start + offset
        if current != target:
            model.ChangeOrder(current, target)
            order.remove(id(ent))
            order.insert(offset, id(ent))


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
    _renumber_nauo_ids(writer.Writer().Model())
    # Same contract, other direction: OCCT appends multi-product style graphs
    # in heap-address order. Reorder them into content order.
    _canonicalize_presentation_styles(writer.Writer().Model())

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
    doc = _create_bin_xcaf_doc(to_export)
    return write_xcaf_doc_step_file(
        doc,
        output_path,
        label=getattr(to_export, "label", None),
        logger=logger,
    )
