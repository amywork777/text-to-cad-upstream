import { useEffect, useRef, useState } from "react";
import { CircleAlert, LoaderCircle } from "lucide-react";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@text-to-cad/ui/primitives/context-menu";
import { TooltipHint } from "@text-to-cad/ui/primitives/tooltip";
import { TREE_INDENT_PX, TreeRowChevron, TreeRowSurface } from "@text-to-cad/ui/primitives/tree-row";
import { FileSheetValueInput } from "../../kit/inspector/FileSheet.js";
import { AUTHOR_DOT_CLASS, AUTHOR_WORDS, authorOf } from "./authors.js";
import { ORIGIN_PLANES, barIndex, planeDetail, rolledBack, sizeName, treeFeatures } from "./editMode.js";
import { AssemblyIcon, FeatureIcon, MateTreeIcon, OriginIcon, ParametersIcon, PartIcon, PlaneIcon, SketchIcon } from "./featureIcons.jsx";
import { buildFailure, nxPlane, treeTitles } from "./nx.js";
import { MassPropertiesIcon } from "./cadIcons.jsx";

const UNIT_MARKS = Object.freeze({ mm: "mm", in: "in" });
// A row under the pointer is the workspace's pale blue, the selected one its deeper blue.
const ROW_HOVER_CLASS = "hover:bg-cad-ws-hover", ROW_SELECTED_CLASS = "bg-cad-ws-selected";
// What a feature that failed to build says, beside its title and on hover.
const BUILD_FAILED = "Did not build";

/** A row's name typed over in place, as SolidWorks' tree renames one: Enter or a click away keeps
 * it, Escape leaves it as it was (`onDone` given the name, or null). */
function RenameInput({ value, onDone }) {
  const [draft, setDraft] = useState(value);
  const done = useRef(false);
  const finish = text => { if (done.current) return; done.current = true; onDone(text); };
  return <input value={draft} aria-label="Name" autoFocus spellCheck={false} maxLength={60}
    className="min-w-0 flex-1 rounded-sm border border-ring bg-background px-1 text-foreground outline-none"
    onFocus={event => event.currentTarget.select()} onChange={event => setDraft(event.currentTarget.value)}
    onClick={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}
    onKeyDown={event => {
      event.stopPropagation();
      if (event.key === "Enter") finish(draft);
      if (event.key === "Escape") finish(null);
    }}
    onBlur={() => finish(draft)} />;
}

/** One row of the tree: its place (depth), its disclosure when it has rows under it, its icon and
 * name. A double-click opens it (`onActivate`: Edit Sketch on a sketch, Edit Feature on a feature),
 * else opens or closes it; a right-click selects it and opens its menu (`menu`, in NX's words and order).
 * While `renaming`, its name is typed over (`onRename`, given the name or null). `warn`: why the
 * feature did not build, marked beside its name with the viewer's warning and said on hover. `author`:
 * who made it (`authors.js`), its dot at the row's right, said on hover. `role`: "treeitem" for a row
 * of the tree; a row above it (the part's name) has none.
 */
function Row({ id, depth, icon, title, detail = "", expanded = null, onToggle = null, onActivate = null, selected, onSelect, onHover, muted = false, menu = null,
  slot = null, renaming = null, onRename = null, check = null, warn = null, author = null, role = "treeitem", drag = null }) {
  const active = Boolean(id) && selected === id;
  const detailed = Boolean(detail) && renaming === null;
  const row = <TreeRowSurface as="div" dense active={active} role={role} aria-selected={role === "treeitem" ? active : undefined}
    aria-expanded={expanded === null ? undefined : expanded} tabIndex={-1} title={warn ? `${BUILD_FAILED}: ${warn}` : undefined}
    className={`cursor-default select-none ${active ? ROW_SELECTED_CLASS : ROW_HOVER_CLASS}`} style={{ paddingLeft: 4 + depth * (TREE_INDENT_PX + 2) }}
    data-cad-edit-tree-row={id || title} data-cad-edit-bar-slot={slot ?? undefined}
    onClick={() => { if (id) onSelect(id); else onToggle?.(); }}
    onContextMenu={() => { if (id && menu?.length) onSelect(id); }}
    onDoubleClick={() => (onActivate ? onActivate() : onToggle?.())}
    onPointerEnter={() => onHover(id || null)} onPointerLeave={() => onHover(null)} {...(drag || {})}>
    <span className="flex w-3 shrink-0 justify-center" onClick={event => { if (onToggle) { event.stopPropagation(); onToggle(); } }}>
      <TreeRowChevron expanded={Boolean(expanded)} branch={expanded !== null} />
    </span>
    {check ? <input type="checkbox" checked={check.checked} disabled={check.disabled} aria-label={check.label}
      className="size-3 shrink-0 cursor-pointer accent-primary disabled:cursor-default"
      onClick={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}
      onChange={event => check.onChange(event.currentTarget.checked)} /> : null}
    {icon}
    {renaming !== null && onRename ? <RenameInput value={renaming} onDone={onRename} />
      : <span className={muted ? "truncate text-muted-foreground" : "truncate"}>{title}</span>}
    {/* The alert card's warning icon, amber as the card draws a warning. */}
    {warn && renaming === null ? <CircleAlert role="img" aria-label={BUILD_FAILED} className="size-3.5 shrink-0 text-amber-500" /> : null}
    {detailed ? <span className="ml-auto truncate pl-2 text-muted-foreground">{detail}</span> : null}
    {/* The timeline's 6px dot; the box around it takes no room of its own, so the pointer finds it more easily. */}
    {author ? <TooltipHint content={AUTHOR_WORDS[author]} side="top">
      <span className={`-m-1 flex shrink-0 p-1 ${detailed ? "" : "ml-auto"}`}>
        <span role="img" aria-label={AUTHOR_WORDS[author]} data-cad-edit-tree-author={author} className={`size-1.5 rounded-full ${AUTHOR_DOT_CLASS[author]}`} />
      </span>
    </TooltipHint> : null}
  </TreeRowSurface>;
  if (!menu?.length) return row;
  return <ContextMenu>
    <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
    <ContextMenuContent className="w-44">
      {menu.map(item => [item.separatorBefore ? <ContextMenuSeparator key={`${item.id}:separator`} /> : null,
        <ContextMenuItem key={item.id} disabled={item.disabled} variant={item.destructive ? "destructive" : "default"} onSelect={item.onSelect}>
          {item.label}
        </ContextMenuItem>])}
    </ContextMenuContent>
  </ContextMenu>;
}

/**
 * The rollback bar, as SolidWorks draws it under a part's features: dragged up between them (or
 * moved a row at a time with the arrow keys) to show the part as it was there. `index` is the item
 * it is above (`count`: past the last). While dragged it stays put and `onPreview` says where it
 * would go (`slotAt`: the place under the pointer); `onMove` places it.
 */
function RollbackBar({ index, count, label, disabled, slotAt, onPreview, onMove }) {
  const drag = useRef(null);
  const place = target => Math.max(1, Math.min(count, target));
  return <div role="slider" aria-label="Rollback bar" aria-orientation="vertical" aria-valuemin={1} aria-valuemax={count}
    aria-valuenow={index} aria-valuetext={label} aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : 0}
    title="Rollback bar: drag it up to see the part as it was there"
    className={`group flex h-3 shrink-0 touch-none items-center px-2 focus-visible:outline-none ${disabled ? "cursor-default opacity-50" : "cursor-grab active:cursor-grabbing"}`}
    data-cad-edit-rollback-bar=""
    onPointerDown={event => {
      if (disabled || event.button !== 0) return;
      // No text selection while dragging; focus taken by hand, so the arrow keys move it after a click.
      event.preventDefault();
      event.currentTarget.focus();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { from: index, at: index };
    }}
    onPointerMove={event => {
      if (!drag.current) return;
      const at = place(slotAt(event.clientY));
      if (at !== drag.current.at) { drag.current.at = at; onPreview(at === drag.current.from ? null : at); }
    }}
    onPointerUp={event => {
      if (!drag.current) return;
      const { from, at } = drag.current;
      drag.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      onPreview(null);
      if (at !== from) onMove(at);
    }}
    onPointerCancel={() => { drag.current = null; onPreview(null); }}
    onKeyDown={event => {
      if (disabled) return;
      const target = { ArrowUp: index - 1, ArrowDown: index + 1, Home: 1, End: count }[event.key];
      if (target === undefined) return;
      event.preventDefault();
      event.stopPropagation();
      if (place(target) !== index) onMove(place(target));
    }}>
    <span className="h-[3px] w-full rounded-full bg-info/70 group-hover:bg-info group-focus-visible:bg-info" />
  </div>;
}

/**
 * A fold above the tree, drawn as a row (its chevron, its icon, its name): the design tree's User
 * Expressions, which NX lists above the model's history. A button, as the tree's rows are not.
 */
function HeadFold({ depth, icon, title, expanded, onToggle }) {
  return <TreeRowSurface as="button" type="button" dense aria-expanded={expanded} data-cad-edit-tree-row={title} onClick={onToggle}
    className={`cursor-default select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 ${ROW_HOVER_CLASS}`}
    style={{ paddingLeft: 4 + depth * (TREE_INDENT_PX + 2) }}>
    <span className="flex w-3 shrink-0 justify-center"><TreeRowChevron expanded={expanded} /></span>
    {icon}<span className="truncate">{title}</span>
  </TreeRowSurface>;
}

/**
 * Add Parameter, as SolidWorks' Equations adds a global variable: a name and a value (a number, or
 * the part's sizes with plain arithmetic), written at the top of the part's script for dimensions
 * and commands to use by name.
 */
function AddParameter({ edit, disabled }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const submit = async event => {
    event.preventDefault();
    if (!name.trim() || !value.trim()) { setError("Type a name and a value."); return; }
    const reply = await edit.addParameter(name.trim(), value.trim());
    if (reply?.ok) { setOpen(false); setName(""); setValue(""); setError(""); }
    else setError(reply?.error || "");
  };
  if (!open) {
    return <button type="button" disabled={disabled} onClick={() => setOpen(true)}
      className="self-start rounded px-1 py-0.5 text-tiny text-muted-foreground hover:bg-sidebar-accent hover:text-foreground disabled:opacity-50">
      + Add expression
    </button>;
  }
  return <form onSubmit={submit} className="flex flex-col gap-1 py-1 pr-1" aria-label="Add expression">
    <div className="flex items-center gap-1">
      <input value={name} onChange={event => { setName(event.target.value); setError(""); }} placeholder="NAME" aria-label="Parameter name" autoFocus
        className="h-6 min-w-0 flex-1 rounded border border-border bg-background px-1.5 text-tiny uppercase text-foreground outline-none focus:border-ring" />
      <span className="text-tiny text-muted-foreground">=</span>
      <input value={value} onChange={event => { setValue(event.target.value); setError(""); }} placeholder="Value" aria-label="Parameter value" inputMode="decimal"
        className="h-6 w-16 rounded border border-border bg-background px-1.5 text-tiny tabular-nums text-foreground outline-none focus:border-ring" />
    </div>
    {error ? <span className="text-tiny leading-4 text-destructive" aria-live="polite">{error}</span> : null}
    <div className="flex justify-end gap-1">
      <button type="button" onClick={() => { setOpen(false); setError(""); }} className="rounded px-1.5 py-0.5 text-tiny text-muted-foreground hover:bg-sidebar-accent">Cancel</button>
      <button type="submit" disabled={disabled} className="rounded bg-primary px-1.5 py-0.5 text-tiny text-primary-foreground disabled:opacity-50">Add</button>
    </div>
  </form>;
}

/**
 * The part's expressions, as NX's Expressions lists them: each named size with its value typed over
 * in place (a change is one number in the part's script), then Add expression. The design tree
 * lists them under its User Expressions, folded, and Expressions in the Inspect tab opens the same
 * list as a panel (`ExpressionsPanel.jsx`).
 */
export function ExpressionRows({ edit }) {
  const params = edit.state?.params || [];
  const disabled = edit.saving || edit.status !== "ready";
  return <>
    {edit.status === "reading" ? <span className="flex items-center gap-1 py-1 text-tiny text-foreground"><LoaderCircle className="size-3.5 shrink-0 animate-spin" aria-hidden="true" />Reading the part</span>
      : params.length === 0 ? <span className="py-1 text-tiny text-muted-foreground">No expressions yet.</span>
        : params.map(param => <div key={param.id} className="flex min-h-7 items-center justify-between gap-2 pr-1">
          <span className="truncate text-tiny text-foreground/80">{sizeName(param.name)}</span>
          <span className="flex shrink-0 items-center gap-1">
            <FileSheetValueInput value={param.text} ariaLabel={`${sizeName(param.name)} value`} disabled={disabled}
              onValueCommit={draft => { const text = String(draft).trim(); if (text && text !== String(param.text)) edit.change({ literal: param.id, text }); }} />
            <span className="w-4 text-micro text-muted-foreground">{UNIT_MARKS[param.unit] || param.unit || ""}</span>
          </span>
        </div>)}
    {edit.status === "reading" || !edit.addParameter ? null : <AddParameter edit={edit} disabled={disabled} />}
  </>;
}

/**
 * Edit mode's design tree, as SolidWorks' FeatureManager lists a part: its name, then Equations folded
 * above the tree (the named sizes, typed over to change), and the tree, which opens with the Origin and
 * the Front, Top and Right Planes and goes on with the features in the order the script makes them,
 * numbered as SolidWorks numbers them (`nx.js`): each with its icon, its own name, its variable's name at the right, a
 * dot past it for who made it (the agent's purple, yours grey, none where it is not known: `authors.js`;
 * a sketch carries its feature's) and a box to suppress it, a solid's sketch under it, a sketch nothing
 * uses yet on a row of its own. An assembly lists its parts as components, each opening to its own
 * features. Selecting a feature draws its dimensions on the model and shows its inputs under the tree;
 * selecting a plane draws it; double-clicking a sketch edits it, and a feature a command made reopens
 * that command's panel (`edit.editFeature`). A row's menu is NX's: Edit Feature, Edit Sketch,
 * Suppress or Unsuppress (`edit.suppress` sets a feature aside, greyed where it is), Rename, Delete
 * (`edit.remove`, as the key does) and Make Current Feature. That one puts the rollback bar just under
 * the feature (`edit.rollTo`), so the part shows as it was there, the features below it greyed and new
 * ones going in at the bar; the bar is dragged to the same effect. The feature a failed build stopped
 * in wears the viewer's warning (`buildFailure`).
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode>,
 *   tree: ReturnType<typeof import("./editMode.js").featureTree>, onEditSketch?: (sketch: object) => void }} props
 */
export default function EditTree({ edit, tree, onEditSketch = () => {}, onOpenPart = null, backTo = null }) {
  const [open, setOpen] = useState(() => new Set(["mates", "datum"]));
  // A selection inside a closed part, or a sketch under a closed feature, opens them to it.
  useEffect(() => {
    const selected = edit.selected || "";
    const featureId = selected.startsWith("sketch:") ? selected.slice("sketch:".length) : selected;
    const owners = [];
    for (const component of tree.components || []) {
      if (component.features.some(feature => feature.id === featureId)) owners.push(component.id);
    }
    if (selected.startsWith("sketch:")) owners.push(featureId);
    if (owners.length) setOpen(current => (owners.every(id => current.has(id)) ? current : new Set([...current, ...owners])));
  }, [edit.selected, tree]);
  const toggle = id => () => setOpen(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const treeRef = useRef(null);
  // Where the rollback bar is being dragged to, while it is.
  const [dragged, setDragged] = useState(null);
  // A feature dragged to another place, as SolidWorks' tree reorders one: the place it would go,
  // while it is (`moving`), and the drag itself, begun once the pointer has gone 4px.
  const [moving, setMoving] = useState(null);
  const reordering = useRef(null);
  const disabled = edit.saving || edit.status !== "ready";
  const rowProps = { selected: edit.selected, onSelect: edit.select, onHover: edit.hover };
  const name = sizeName(edit.state?.name || "") || "Part";
  // The feature a failed build stopped in, to be marked: the one with the line the engine says it stopped at, or with the call into the helper that did.
  const failure = buildFailure(tree, edit.error, edit.failure);
  // A row's menu, in NX's words and order: Edit Feature on a feature a command made, Edit Sketch
  // where it has a sketch to edit, Suppress or Unsuppress, Rename, Delete (on a feature or a sketch of
  // its own: a feature's sketch goes with its feature), Make Current Feature.
  const busy = disabled || Boolean(edit.sketch);
  // Edit Feature works on a part's own body: in an assembly, a part is opened to edit its features.
  const editable = feature => Boolean(feature.edit) && !tree.assembly;
  const featureItem = feature => (editable(feature) ? [{ id: "edit-parameters", label: "Edit Feature", disabled: busy, onSelect: () => edit.editFeature(feature) }] : []);
  const suppressItem = feature => ({ id: "suppress", label: feature.suppressed ? "Unsuppress" : "Suppress", disabled: busy,
    onSelect: () => void edit.suppress(feature.id, tree, !feature.suppressed) });
  // A suppressed feature, and the sketch under it, greyed; so are the features below the rollback bar.
  const greyed = icon => <span className="flex shrink-0 opacity-50">{icon}</span>;
  const rolled = rolledBack(tree, edit.bar);
  const partItems = tree.assembly ? [] : tree.features;
  // Each row's title as SolidWorks' design tree numbers it (Boss-Extrude2), a part's own or each of an assembly's.
  const titles = treeTitles(tree);
  const titleOf = row => titles.get(row.id) || row.title;
  const barAt = barIndex(tree, edit.bar);
  // SolidWorks' Rollback: the rollback bar just above the feature, it and what follows rolled back;
  // and, while the bar is up, Roll to End, the bar past the last feature again.
  const currentItem = feature => {
    const index = partItems.findIndex(each => each.id === feature.id);
    if (index < 0) return [];
    return [{ id: "rollback", label: "Rollback", disabled: busy || barAt === index, onSelect: () => void edit.rollTo(feature.id) },
      ...(barAt < partItems.length ? [{ id: "roll-to-end", label: "Roll to End", disabled: busy, onSelect: () => void edit.rollTo(null) }] : [])];
  };
  const editItem = sketch => (sketch?.constrained ? [{ id: "edit-sketch", label: "Edit Sketch", disabled, onSelect: () => onEditSketch(sketch) }] : []);
  const deleteItem = id => ({ id: "delete", label: "Delete", destructive: true, disabled: disabled || Boolean(edit.sketch),
    onSelect: () => void edit.remove(id, tree) });
  // The groups a menu is made of, each set off from the one before by a line: what edits the row, what
  // changes it, what makes it current.
  const menuOf = (...groups) => groups.filter(group => group.length)
    .flatMap((group, index) => group.map((item, at) => (index > 0 && at === 0 ? { ...item, separatorBefore: true } : item)));
  // Rename, from the menu or F2: the row's name typed over in place, written into the script.
  const renameItem = id => ({ id: "rename", label: "Rename", disabled: busy || tree.assembly, onSelect: () => edit.startRename(id) });
  const renamingOf = (id, title, target) => (edit.renaming === id && !busy && !tree.assembly
    ? { renaming: title, onRename: name => (name === null ? edit.stopRename() : void edit.rename(target, name)) } : {});
  // Who made a feature, its dot at its row's right; a sketch has no author of its own, and carries its feature's.
  const authorAt = id => authorOf(edit.state?.authors, id);
  const sketchRow = (sketch, depth, own = null, muted = false, author = null) => (
    <Row key={sketch.id} id={sketch.id} depth={depth} icon={muted ? greyed(<SketchIcon />) : <SketchIcon />} muted={muted}
      title={titleOf(sketch)} detail={sketch.plane && sketch.plane !== "Plane" ? `${nxPlane(sketch.plane)}${sketch.offset ? `, ${sketch.offset} ${edit.state?.units || ""}`.trimEnd() : ""}` : ""}
      slot={own ? partItems.findIndex(each => each.id === own.id) : null} author={author} drag={own ? dragOf(own.id) : null}
      onActivate={disabled ? null : () => onEditSketch(sketch)} warn={failure?.id === sketch.id ? failure.why : null}
      {...(sketch.constrained ? renamingOf(sketch.id, sketch.title, { sketch: { file: sketch.file, line: sketch.line }, title: sketch.title }) : {})}
      menu={menuOf(editItem(sketch), [...(sketch.constrained ? [renameItem(sketch.id)] : []), ...(own ? [deleteItem(sketch.id)] : [])], own ? currentItem(own) : [])}
      {...rowProps} />);
  const dragOf = id => (busy || tree.assembly ? null : {
    onPointerDown: event => {
      if (event.button !== 0 || (event.target instanceof Element && event.target.closest("input, button"))) return;
      reordering.current = { id, y: event.clientY, at: null };
    },
    onPointerMove: event => {
      const drag = reordering.current;
      if (drag?.id !== id || (drag.at === null && Math.abs(event.clientY - drag.y) < 4)) return;
      if (drag.at === null) event.currentTarget.setPointerCapture?.(event.pointerId);
      const at = slotAt(event.clientY);
      if (at !== drag.at) { drag.at = at; setMoving(at); }
    },
    onPointerUp: event => {
      const drag = reordering.current;
      reordering.current = null;
      if (drag?.at === null || drag?.id !== id) return;
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      setMoving(null);
      void edit.reorder(id, drag.at, tree);
    },
    onPointerCancel: () => { reordering.current = null; setMoving(null); },
  });
  const featureRows = (feature, depth) => {
    const out = rolled.has(feature.id);
    const author = authorAt(feature.id);
    if (feature.kind === "Sketch") return [sketchRow(feature.sketch, depth, feature, out, author)];
    const branch = Boolean(feature.sketch);
    const expanded = open.has(feature.id);
    const detail = feature.suppressed ? "Suppressed" : feature.kind === "Plane" ? planeDetail(feature, edit.state?.units || "")
      : `${feature.name}${feature.count > 1 ? ` ×${feature.count}` : ""}`;
    const grey = feature.suppressed || out;
    const slot = partItems.findIndex(each => each.id === feature.id);
    return [
      <Row key={feature.id} id={feature.id} depth={depth} title={titleOf(feature)} detail={detail} muted={grey}
        check={{ checked: !feature.suppressed, disabled: busy, label: `${titleOf(feature)}: ${feature.suppressed ? "suppressed" : "active"}`,
          onChange: active => void edit.suppress(feature.id, tree, !active) }}
        icon={grey ? greyed(<FeatureIcon kind={feature.kind} />) : <FeatureIcon kind={feature.kind} />}
        expanded={branch ? expanded : null} onToggle={branch ? toggle(feature.id) : null} slot={slot < 0 ? null : slot}
        onActivate={editable(feature) && !busy ? () => edit.editFeature(feature) : null}
        {...renamingOf(feature.id, feature.title, { feature: feature.id, title: feature.title })}
        warn={failure?.id === feature.id ? failure.why : null} author={author} drag={feature.suppressed ? null : dragOf(feature.id)}
        menu={menuOf([...featureItem(feature), ...editItem(feature.sketch)], [suppressItem(feature), renameItem(feature.id), deleteItem(feature.id)], currentItem(feature))}
        {...rowProps} />,
      branch && expanded ? sketchRow(feature.sketch, depth + 1, null, grey, author) : null,
    ];
  };
  const features = (list, depth) => list.flatMap(feature => featureRows(feature, depth));
  // The bar's place as the pointer drags it: above the first row whose middle is below the pointer.
  const slotAt = clientY => {
    const slots = [...(treeRef.current?.querySelectorAll("[data-cad-edit-bar-slot]") || [])];
    const below = slots.find(slot => clientY < slot.getBoundingClientRect().top + slot.getBoundingClientRect().height / 2);
    return below ? Number(below.getAttribute("data-cad-edit-bar-slot")) : partItems.length;
  };
  const bar = partItems.length > 1 && edit.status === "ready" ? <RollbackBar key="rollback-bar" index={barAt} count={partItems.length}
    label={barAt >= partItems.length ? "At the end" : `Above ${titleOf(partItems[barAt])}`} disabled={busy}
    slotAt={slotAt} onPreview={setDragged}
    onMove={index => void edit.rollTo(index >= partItems.length ? null : partItems[index].id)} /> : null;
  // Where a dragged bar would go, drawn faintly until it is let go; it takes no room, so the rows
  // under the pointer stay put.
  const preview = <div key="rollback-preview" aria-hidden="true" className="relative h-0 shrink-0">
    <span className="absolute inset-x-2 -top-px h-0.5 rounded-full bg-info/60" />
  </div>;
  // Where a dragged feature would go, drawn as the bar's preview is, in the selection's color.
  const dropLine = <div key="reorder-preview" aria-hidden="true" className="relative h-0 shrink-0" data-cad-edit-drop="">
    <span className="absolute inset-x-2 -top-px h-0.5 rounded-full bg-primary" />
  </div>;
  // The part's features, the rollback bar among them where it is.
  const partRows = () => {
    const groups = partItems.map(feature => featureRows(feature, 1));
    const marks = [[barAt, bar], ...(dragged !== null && dragged !== barAt ? [[dragged, preview]] : []),
      ...(moving !== null ? [[moving, dropLine]] : [])];
    return groups.flatMap((group, index) => [...marks.filter(([at]) => at === index).map(([, mark]) => mark), ...group])
      .concat(marks.filter(([at]) => at >= groups.length).map(([, mark]) => mark));
  };
  // The Delete key on the selected feature, as SolidWorks takes it; in sketch mode the key is the
  // sketch's (its entities).
  const onKeyDown = event => {
    if ((event.key !== "Delete" && event.key !== "Backspace") || disabled || edit.sketch || !edit.selected) return;
    if (event.target instanceof Element && event.target.closest("input, textarea, [contenteditable]")) return;
    const id = edit.selected;
    if (!treeFeatures(tree).some(feature => feature.id === id || feature.sketch?.id === id)) return;
    event.preventDefault();
    void edit.remove(id, tree);
  };
  // An assembly's Mates, as SolidWorks lists them under its parts: each by its name and the parts it
  // places, deleted from its menu (its part goes back where it was).
  const mates = tree.assembly ? edit.state?.mates || [] : [];
  const mateRows = () => (mates.length ? [
    <Row key="mates" id="mates" depth={1} icon={<MateTreeIcon />} title="Mates" expanded={open.has("mates")} onToggle={toggle("mates")} {...rowProps} />,
    ...(open.has("mates") ? mates.map(mate => <Row key={mate.label} id={`mate:${mate.label}`} depth={2} icon={<MateTreeIcon />}
      title={`${mate.name} (${mate.parts.join(", ")})`} {...rowProps}
      menu={[{ id: "delete", label: "Delete", disabled: busy, onSelect: () => void edit.mate({ delete: mate.label }) }]} />) : []),
  ] : []);
  return <div ref={treeRef} className="flex flex-col px-1 py-1" data-cad-edit-tree="" onKeyDown={onKeyDown}>
    {backTo ? <button type="button" className="flex h-7 shrink-0 items-center gap-1.5 rounded-md px-1 text-left text-tiny text-muted-foreground hover:bg-accent/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45"
      onClick={backTo.open} data-cad-edit-back="">
      <AssemblyIcon /><span className="truncate">{`Back to ${backTo.title}`}</span>
    </button> : null}
    {/* The part's own menu: its Edit Object Display and its Measure Bodies, in the toolbar's words. */}
    <Row id="" depth={0} role="none" icon={tree.assembly ? <AssemblyIcon /> : <PartIcon />} title={name} {...rowProps}
      menu={tree.assembly ? null : [{ id: "appearance", label: "Appearance", disabled: busy, onSelect: () => edit.inspect("appearance") },
        { id: "mass", label: "Mass Properties", disabled: busy, onSelect: () => edit.inspect("mass") }]} />
    {/* The part's named sizes, as NX's User Expressions holds them: folded, above the tree. */}
    <HeadFold depth={1} icon={<ParametersIcon />} title="Equations" expanded={open.has("expressions")} onToggle={toggle("expressions")} />
    {open.has("expressions") ? <div role="group" aria-label="Equations" className="flex flex-col pb-1" style={{ paddingLeft: 4 + 2 * (TREE_INDENT_PX + 2) }}>
      <ExpressionRows edit={edit} />
    </div> : null}
    <div role="tree" aria-label="FeatureManager design tree" className="flex flex-col">
      {/* The part's material, as SolidWorks' tree lists it above the planes: Edit Material opens Mass Properties' picker. */}
      {!tree.assembly ? <Row id="material" depth={1} icon={<MassPropertiesIcon className="size-4" />}
        title={edit.state?.materialName || "Material <not specified>"} onActivate={() => edit.inspect("mass")}
        menu={[{ id: "edit-material", label: "Edit Material", disabled: busy, onSelect: () => edit.inspect("mass") }]} {...rowProps} /> : null}
      {/* The Origin and its planes, before the features. */}
      <Row id="origin" depth={1} icon={<OriginIcon />} title="Origin" expanded={open.has("datum")} onToggle={toggle("datum")} {...rowProps} />
      {open.has("datum") ? ORIGIN_PLANES.map(plane => <Row key={plane} id={`plane:${plane}`} depth={2} icon={<PlaneIcon />} title={nxPlane(plane)} {...rowProps} />) : null}
      {tree.assembly && onOpenPart && tree.components.some(component => component.document || component.step)
        ? <p className="px-2 py-1 text-tiny leading-4 text-muted-foreground">Double-click a part to open it and model it.</p> : null}
      {tree.assembly
        ? tree.components.flatMap(component => [
          // A part of the assembly opens on its own to be modeled, as SolidWorks' Open Part opens it.
          <Row key={component.id} id={component.id} depth={1} icon={<PartIcon />} title={component.title}
            expanded={open.has(component.id)} onToggle={toggle(component.id)}
            onActivate={(component.document || component.step) && onOpenPart ? () => onOpenPart(component) : null}
            menu={(component.document || component.step) && onOpenPart ? [{ id: "open-part", label: "Open Part", onSelect: () => onOpenPart(component) }] : null}
            {...rowProps} />,
          ...(open.has(component.id) ? features(component.features, 2) : []),
        ]).concat(mateRows())
        : partRows()}
    </div>
  </div>;
}
