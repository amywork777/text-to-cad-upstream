import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, ChevronsRight, LoaderCircle, Search } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@text-to-cad/ui/primitives/dropdown-menu";
import { Progress } from "@text-to-cad/ui/primitives/progress";
import { ToolbarButton } from "@text-to-cad/ui/primitives/toolbar-button";
import { TooltipHint } from "@text-to-cad/ui/primitives/tooltip";
import { cn } from "@text-to-cad/ui/utils";
import { FLOATING_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { AppearanceIcon, COMMAND_ICONS, CompareIcon, DraftAnalysisIcon, InterferenceIcon, DrawingIcon, ExitSketchIcon, ExpressionsIcon, MassPropertiesIcon, InsertComponentIcon, MateIcon, RedoIcon, SketchIcon, UndoIcon } from "./cadIcons.jsx";
import { EDIT_COMMANDS, buildingText, busyState, unitWord } from "./editMode.js";
import { SKETCH_ENTITIES, SKETCH_FAMILIES, SKETCH_MODIFY, SKETCH_TOOLS, sketchKey } from "./sketchMode.js";
import { ConstructionIcon, NormalToIcon, SKETCH_TOOL_ICONS } from "./sketchIcons.jsx";
import { SOLID_GROUPS, booleanOf, nxCommand, workspaceTabs } from "./nx.js";
import CommandSearchBox from "./CommandSearchBox.jsx";

// The viewer's tools the tabs place, by id, under SolidWorks' names (Clip is its Section View).
const LABELS = Object.freeze({ clip: "Section View", select: "Select", exploded: "Exploded View" });
// A sketch tool family's button name, as SolidWorks' flyouts are named.
const FAMILY_NAMES = Object.freeze({ rectangle: "Rectangle", circle: "Circle", arc: "Arc", slot: "Slot", move_entities: "Move Entities" });
// Each command a picture large enough to tell apart, as SolidWorks' CommandManager draws its own: every
// one the icon generator's (`cadIcons.jsx`, `sketchIcons.jsx`), the view's tools as the strip shows them.
// Under the pointer the workspace's pale blue (`--cad-ws-hover`), pressed its deeper one (`PRESSED_CLASS`).
const BUTTON_CLASS = "flex h-[3.875rem] min-w-12 flex-col items-center justify-start gap-1 rounded-md px-1 pt-1.5 text-tiny leading-none text-sidebar-foreground/85 transition-colors hover:bg-cad-ws-hover hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-6 [&_svg]:shrink-0";
const PRESSED_CLASS = "bg-cad-ws-selected text-sidebar-accent-foreground hover:bg-cad-ws-selected";
// A long name wraps to two lines under its icon, as SolidWorks' CommandManager sets them; without
// names (`compact`) the buttons narrow to their icons.
const LABEL_CLASS = "max-w-[4.75rem] whitespace-normal text-center leading-[1.1]";
// The view's own controls the frame hands over (Projection, Display, Preview: the strip's small tiles), lit as
// the toolbar's buttons are: the workspace's pale blue under the pointer, its deeper one while a menu is open.
const VIEW_CONTROLS_CLASS = "flex shrink-0 items-center gap-0.5 [&_button:hover]:bg-cad-ws-hover [&_button[aria-expanded=true]]:bg-cad-ws-selected";
// A tab: its name in capitals, the one in front underlined.
// The command search's button at the tab row's right, a field to look at as NX's Command Finder is.
const FINDER_CLASS = "flex h-5 w-44 min-w-0 shrink items-center gap-1.5 rounded-md border border-border bg-background px-1.5 text-tiny text-muted-foreground transition-colors hover:bg-cad-ws-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45";
const TAB_CLASS = "flex items-center border-b-2 border-transparent px-2.5 text-tiny uppercase leading-none tracking-wider text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45";
// A group's title, in capitals under its buttons; where it is the group's menu it is a button too.
const TITLE_CLASS = "text-micro uppercase leading-3 tracking-wider text-muted-foreground";
const STATUS_CLASSES = Object.freeze({ "Fully defined": "text-foreground", "Under defined": "text-blue-600 dark:text-blue-400",
  "Over defined": "text-red-600 dark:text-red-400" });
// The More button's box, before it is first laid out.
const MORE_WIDTH_PX = 46;
const ALL_NAMED = Object.freeze({ compact: false, count: Infinity });

function RibbonButton({ label, icon, active, disabled = false, description, onClick, compact = false, hint }) {
  return <TooltipHint content={hint || label}>
    <button type="button" aria-label={label} aria-pressed={active} aria-description={description} disabled={disabled}
      className={cn(BUTTON_CLASS, active && PRESSED_CLASS, compact && "min-w-9 justify-center pt-0")}
      onClick={onClick}>
      {icon}
      {compact ? null : <span className={LABEL_CLASS}>{label}</span>}
    </button>
  </TooltipHint>;
}

/** A group: its buttons over its title, which is its menu (`menu`) where the group has one; `end`, at the row's right end. */
function RibbonGroup({ title, folded = false, end = false, menu = null, children }) {
  return <div role="group" aria-label={title} aria-hidden={folded || undefined} data-cad-ribbon-group=""
    className={cn("flex shrink-0 flex-col items-center border-r border-border px-1 last:border-r-0", end && "ml-auto", folded && "invisible")}>
    <div className="flex items-center gap-0.5 pt-1">{children}</div>
    {menu || <span className={cn(TITLE_CLASS, "pb-1 pt-0.5")}>{title}</span>}
  </div>;
}

/**
 * How the ribbon's groups fit, giving way as SolidWorks' CommandManager does: first the names go
 * (`compact`: the icons alone, each name in its tooltip), then whole groups fold from the right
 * behind the More button (`count`: the groups shown; Infinity, all of them). Each layout is
 * measured before it is painted. A folded group keeps its place, unseen past the edge, so each
 * group's right edge reads the same whichever are folded; the width the groups took with their
 * names is kept, to know when they fit again. The edges are the groups' widths summed, as the row
 * packs them with no gap: where they place themselves (a group at the row's end) does
 * not change what they need.
 */
function useRibbonFit(rowRef, moreRef, key) {
  const [fit, setFit] = useState(ALL_NAMED);
  const named = useRef(0);
  const measure = useCallback(() => {
    const row = rowRef.current;
    const groups = row ? [...row.querySelectorAll(":scope > [data-cad-ribbon-group]")] : [];
    if (!groups.length) return;
    const more = moreRef.current?.offsetWidth || 0;
    // The room the groups have with no More button beside them.
    const room = row.clientWidth + more + 1;
    let packed = 0;
    const rights = groups.map(group => (packed += group.offsetWidth));
    let next;
    if (row.dataset.compact !== "true") {
      named.current = rights.at(-1);
      next = named.current <= room ? ALL_NAMED : { compact: true, count: Infinity };
    } else if (!named.current || named.current <= room) {
      next = ALL_NAMED; // the names fit again, or their width is not known yet: shown to learn it
    } else {
      next = { compact: true, count: rights.at(-1) <= room ? Infinity : rights.filter(right => right <= room - (more || MORE_WIDTH_PX)).length };
    }
    setFit(current => (current.compact === next.compact && current.count === next.count ? current : next));
  }, [rowRef, moreRef]);
  // Other groups or names: their width with names is learnt again.
  useLayoutEffect(() => { named.current = 0; }, [key]);
  useLayoutEffect(measure, [measure, key, fit]);
  // A change in the room is measured on the next frame.
  useEffect(() => {
    const row = rowRef.current;
    if (!row || typeof ResizeObserver === "undefined") return undefined;
    let frame = 0;
    const observer = new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure); });
    observer.observe(row);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, [rowRef, measure]);
  return fit;
}

/** A sketch tool family's flyout, as SolidWorks' Sketch tab has them: a chevron after its button, its tools in a menu. */
function FamilyMenu({ label, items, onPick }) {
  return <DropdownMenu modal={false}>
    <TooltipHint content={`${label} tools`}>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label={`${label} tools`}
          className="-ml-1 flex h-[3.875rem] w-3.5 shrink-0 items-start justify-center rounded-md pt-3 text-sidebar-foreground/60 transition-colors hover:bg-cad-ws-hover hover:text-sidebar-accent-foreground aria-expanded:bg-cad-ws-selected [&_svg]:size-3">
          <ChevronDown aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
    </TooltipHint>
    <DropdownMenuContent align="start" sideOffset={4} collisionPadding={8} aria-label={`${label} tools`}
      className={cn(FLOATING_SURFACE_CLASS, "w-60 data-[state=closed]:animate-none!")}>
      {items.map(item => <DropdownMenuCheckboxItem key={item.id} checked={item.active} disabled={item.disabled}
        onSelect={() => { onPick(item.id); item.onClick(); }}>{item.icon}{item.hint || item.label}</DropdownMenuCheckboxItem>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}

/** A group's items as a menu lists them, each with its icon: a tool or command in hand is ticked. */
function GroupItems({ items }) {
  return items.flatMap(item => item.variants || [item]).map(item => typeof item.active === "boolean"
    ? <DropdownMenuCheckboxItem key={item.id} checked={item.active} disabled={item.disabled} onSelect={() => item.onClick()}>
      {item.icon}{item.label}
    </DropdownMenuCheckboxItem>
    : <DropdownMenuItem key={item.id} disabled={item.disabled} onSelect={() => item.onClick()}>{item.icon}{item.label}</DropdownMenuItem>);
}

/**
 * A group's title as its menu, as Fusion's toolbar has them: a small arrow after the title, every item of the group in the menu.
 * Called "<title> commands", its title in its name: a group and its command can be called alike (Select, Measure,
 * Expressions, Exploded Views), and a button called by that name is the command.
 */
function GroupMenu({ title, items }) {
  return <DropdownMenu modal={false}>
    <DropdownMenuTrigger asChild>
      <button type="button" aria-label={`${title} commands`} className={cn(TITLE_CLASS, "mb-1 mt-0.5 flex items-center gap-0.5 rounded-sm px-1 transition-colors hover:bg-cad-ws-hover hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 aria-expanded:bg-cad-ws-selected")}>
        {title}<ChevronDown className="size-2.5 shrink-0" aria-hidden="true" />
      </button>
    </DropdownMenuTrigger>
    {/* Closes with no exit animation, so a quick second press always reaches the title. */}
    <DropdownMenuContent align="start" sideOffset={4} collisionPadding={8} aria-label={title}
      className={cn(FLOATING_SURFACE_CLASS, "w-56 data-[state=closed]:animate-none!")}>
      <GroupItems items={items} />
    </DropdownMenuContent>
  </DropdownMenu>;
}

/** The groups that did not fit, as one menu: each group's title, then its commands. */
function MoreMenu({ groups }) {
  return <DropdownMenu modal={false}>
    <TooltipHint content="More commands">
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label="More commands" className={cn(BUTTON_CLASS, "min-w-9 justify-center pt-0 aria-expanded:bg-cad-ws-selected")}>
          <ChevronsRight aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
    </TooltipHint>
    {/* Closes with no exit animation, so a quick second press always reaches the button. */}
    <DropdownMenuContent align="end" sideOffset={4} collisionPadding={8} aria-label="More commands"
      className={cn(FLOATING_SURFACE_CLASS, "w-56 data-[state=closed]:animate-none!")}>
      {groups.map((group, index) => <Fragment key={group.title}>
        {index ? <DropdownMenuSeparator /> : null}
        <DropdownMenuLabel className="text-micro uppercase tracking-wider text-muted-foreground">{group.title}</DropdownMenuLabel>
        <GroupItems items={group.items} />
      </Fragment>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}

// The buttons a group draws: its first `shown` items, all of them where the group has no menu of its own.
const shownItems = group => (group.shown === undefined ? group.items : group.items.slice(0, group.shown));

/**
 * The ribbon's groups (`{ title, items, shown? }`, each item a button's `{ id, label, icon, active?,
 * disabled?, description?, menu?, onClick }`) in one row, and what does not fit in its More menu.
 * A group with `shown` draws that many of its items as buttons and its title as a menu of all of
 * them; one without draws them all, under a plain title.
 */
function RibbonGroups({ groups }) {
  const rowRef = useRef(null);
  const moreRef = useRef(null);
  const key = groups.map(group => `${group.title}:${shownItems(group).map(item => item.label).join(",")}`).join("|");
  const fit = useRibbonFit(rowRef, moreRef, key);
  const folded = groups.slice(fit.count);
  return <>
    <div ref={rowRef} data-compact={fit.compact ? "true" : "false"} className="relative flex min-w-0 flex-1 items-stretch overflow-hidden">
      {groups.map((group, index) => <RibbonGroup key={group.title} title={group.title} folded={index >= fit.count} end={group.end}
        menu={group.shown === undefined ? null : <GroupMenu title={group.title} items={group.items} />}>
        {/* A tool's settings (Select's filter) are its chevron after its button, as on the strip. */}
        {shownItems(group).map(({ id, menu, ...item }) => <Fragment key={id}><RibbonButton {...item} compact={fit.compact} />{menu || null}</Fragment>)}
      </RibbonGroup>)}
    </div>
    {folded.length ? <div ref={moreRef} className="flex shrink-0 flex-col items-center border-x border-border px-1" data-cad-ribbon-more="">
      <div className="flex items-center pt-1"><MoreMenu groups={folded} /></div>
      <span className={cn(TITLE_CLASS, "pb-1 pt-0.5")}>More</span>
    </div> : null}
  </>;
}

/**
 * What the command search may run, `{ id, label, icon, disabled, description, run }` for each item of `groups` (a family's
 * flyout tools too) and of `extras`, by its id: the toolbar's own items, so the search lists what the toolbar has, named, pictured
 * and dimmed as the toolbar has it, and nothing it has not. `run` is what the item says it does to be run, else its click, which is
 * left alone while its tool or panel is already on, as the strip's letter leaves a tool already in hand (`pressToolKey`).
 */
function searchable(groups, extras = []) {
  const found = new Map();
  for (const item of [...groups.flatMap(group => group.items.flatMap(each => each.variants || [each])), ...extras]) {
    if (found.has(item.id)) continue;
    found.set(item.id, { id: item.id, label: item.label, icon: item.icon, disabled: Boolean(item.disabled), description: item.description,
      run: item.run || (() => { if (!item.active) item.onClick(); }) });
  }
  return [...found.values()];
}

/**
 * Edit mode's toolbar, across the top of the viewer: Fusion's arrangement in NX's words. Its tab
 * row has Undo and Redo of the hand changes at the left, the tabs after them, and at the right the
 * part's units and where its build stands (or the sketch and how defined it is). Solid holds the
 * modeling commands in groups (`SOLID_GROUPS`: Create, Modify, Construct), each opening its
 * dialog, then Select (Measure and Section View are on the Evaluate tab). Sketch
 * holds the Sketch command (Edit Sketch on a sketch selected); Evaluate measures and checks the
 * part, orients and colors its view and lists its Expressions; Assemble, for an assembly, holds
 * Assembly Constraints and Exploded Views; Drafting the part's drawing. A group shows its
 * most-used commands as buttons over its title, which is its menu of them all. While a sketch is
 * edited the Sketch tab alone is up, holding the sketch's tools as NX's sketch task environment
 * does: Finish Sketch (back to Solid), the curves to draw and edit (Quick Trim, Offset Curve...),
 * Rapid Dimension, and the features to make of it. A narrow view keeps the icons and drops the
 * names, then folds the groups at the right into a More menu. At the tab row's right end, before
 * where the part stands, the view's own (`view`, the frame's: `RendererShell`'s `ribbon(tools, view)`):
 * its controls, Projection, Display and Preview, and the view catching up.
 *
 * S asks for the command search (`edit.findAsked` counts the asks, `useEditShortcuts.js`): a box under
 * the toolbar (`CommandSearchBox.jsx`) that finds any button of the toolbar by name, on whichever tab, and
 * runs it as pressing the button does (`searchable`).
 *
 * @param {{ tools: import("../../kit/tools/FloatingToolBar.js").ViewportTool[],
 *   edit: ReturnType<typeof import("./useEditMode.js").useEditMode>, onCommand?: (id: string) => void,
 *   onSketch?: () => void, sketchLabel?: string, onNormalTo?: (() => void) | null,
 *   view?: { controls?: import("react").ReactNode, status?: import("react").ReactNode } | null }} props
 *   `onCommand` opens a command (the surface turns Select to what it picks); `onSketch` is the
 *   Sketch button (`sketchLabel`: "Edit Sketch" while a sketch is selected). The workspace has no agent, so
 *   the toolbar has no Ask, Add to context or Annotate.
 */
export default function EditRibbon({ tools, edit, onCommand = id => edit.open(id), onSketch = () => edit.startPicking(), sketchLabel = "Sketch",
  canOpenParts = false, onNormalTo = null, view = null }) {
  const byId = new Map(tools.map(tool => [tool.id, tool]));
  // The tab in front, as NX keeps it while the part is open.
  const [tab, setTab] = useState("solid");
  const state = edit.state;
  const sketch = edit.sketch;
  // A sketch ends, Finish Sketch or not: the toolbar returns to Solid, not to the tab the sketch was opened from.
  const [sketched, setSketched] = useState(Boolean(sketch));
  if (sketched !== Boolean(sketch)) {
    setSketched(Boolean(sketch));
    if (!sketch) setTab("solid");
  }
  // Each sketch tool family's tool last picked from its flyout, shown as its button.
  const [lastOfFamily, setLastOfFamily] = useState({});
  // The command search, opened by each ask made while this toolbar stands (S: `edit.findCommand`), and not by one made before it did.
  const [finding, setFinding] = useState(false);
  const [asked, setAsked] = useState(edit.findAsked);
  if (asked !== edit.findAsked) {
    setAsked(edit.findAsked);
    setFinding(true);
  }
  // What it is busy with, said with a spinner and a line along the ribbon's foot, as a CAD tool's
  // status bar shows a rebuild: never a word alone that could be a label.
  const busy = busyState(edit);
  const status = busy?.text || buildingText(state?.building) || (edit.status === "ready" ? "Saved" : "");
  const commandsIdle = edit.status !== "ready" || edit.saving || edit.rolling;
  // An assembly places its parts: a part is modeled on its own, opened from the design tree, as
  // SolidWorks models a part in its own window.
  const placing = Boolean(edit.state?.components?.length);
  const modelingOff = commandsIdle || placing;
  const placingWords = !placing ? undefined : canOpenParts
    ? "An assembly places its parts. Double-click a part in the design tree to open it and model it."
    : "An assembly places its parts. Ask the agent to change a part.";
  const commandIcon = id => { const Icon = COMMAND_ICONS[id]; return <Icon aria-hidden="true" />; };
  const toolItem = tool => ({ id: tool.id, label: LABELS[tool.id] || tool.label, icon: tool.icon, active: tool.active === true,
    disabled: tool.disabled, description: tool.description, menu: tool.menu, onClick: () => tool.onSelect() });
  // The tab row: Undo and Redo as small icons at its left, the tabs, and at its right where the part stands.
  const tabRow = (list, active, onPick, end) => <div data-cad-ribbon-tabs="" className="flex h-7 shrink-0 items-center gap-0.5 border-b border-border px-1.5">
    <div className="flex shrink-0 items-center gap-0.5 pr-2">
      <ToolbarButton label="Undo" className="hover:bg-cad-ws-hover" disabled={!edit.canUndo} onClick={() => void edit.undo()}><UndoIcon className="size-4" /></ToolbarButton>
      <ToolbarButton label="Redo" className="hover:bg-cad-ws-hover" disabled={!edit.canRedo} onClick={() => void edit.redo()}><RedoIcon className="size-4" /></ToolbarButton>
    </div>
    <div role="tablist" aria-label="Ribbon tabs" className="flex h-full shrink-0 items-stretch gap-0.5">
      {list.map(each => <button key={each.id} type="button" role="tab" aria-selected={each.id === active}
        className={cn(TAB_CLASS, each.id === active && "border-info font-medium text-foreground")}
        onClick={() => onPick(each.id)}>{each.title}</button>)}
    </div>
    <div className="ml-auto flex min-w-0 items-center gap-2 pl-2">
      {/* The command search in view, as NX's Command Finder is, S its key. */}
      <button type="button" data-cad-command-finder="" aria-haspopup="dialog" aria-expanded={finding} title="Search commands (S)"
        className={FINDER_CLASS} onClick={() => setFinding(true)}>
        <Search aria-hidden="true" className="size-3.5 shrink-0" />
        <span className="min-w-0 truncate">Search commands</span>
        <kbd className="ml-auto shrink-0 rounded border border-border px-1 font-sans text-[0.625rem] leading-3">S</kbd>
      </button>
      {view?.controls ? <div className={VIEW_CONTROLS_CLASS} data-cad-ribbon-view="">{view.controls}</div> : null}
      {view?.status || null}
      <div className="flex min-w-0 items-center gap-2 text-tiny leading-4" aria-live="polite">{end}</div>
    </div>
  </div>;
  // `finds`: the items the command search may run, whichever tab each is on (`searchable`); the box is the toolbar's neighbour, for the toolbar clips.
  const ribbon = (label, groups, end, { tabs, active, onPick, key = label, sketching = false, finds }) => <>
    <div data-cad-ribbon="" data-cad-sketch-ribbon={sketching ? "" : undefined}
      aria-busy={busy ? true : undefined}
      className="relative flex min-h-0 shrink-0 flex-col overflow-hidden border-b border-border bg-background" role="toolbar" aria-label={label}>
      {tabRow(tabs, active, onPick, end)}
      <div className="flex min-h-0 items-stretch overflow-hidden">
        <RibbonGroups key={key} groups={groups} />
      </div>
      {busy ? <Progress value={busy.progress} className="absolute inset-x-0 bottom-0" aria-label={busy.text} /> : null}
    </div>
    {finding ? <CommandSearchBox items={finds()} sketching={sketching} onClose={() => setFinding(false)} /> : null}
  </>;
  const statusLine = (text, failed = false) => <span className={cn("flex min-w-0 items-center gap-1",
    busy ? "text-foreground" : failed ? "text-destructive" : "text-muted-foreground")}>
    {busy ? <LoaderCircle className="size-3.5 shrink-0 animate-spin" aria-hidden="true" /> : null}<span className="truncate">{text}</span>
  </span>;

  if (sketch) {
    const tool = id => SKETCH_TOOLS.find(each => each.id === id);
    const sketchItem = each => {
      const Icon = SKETCH_TOOL_ICONS[each.id];
      const active = edit.sketchTool === each.id;
      const onClick = () => {
        // Entities selected with the line to mirror them about last: mirrored at once, as SolidWorks does.
        const picked = edit.sketchSelection;
        const about = (sketch.state?.curves || []).find(curve => curve.id === picked.at(-1));
        if (each.id === "mirror" && !active && picked.length > 1 && about?.kind === "line" && !about.derived) {
          void edit.sketchOp({ kind: "mirror", items: picked.slice(0, -1), about: about.id }).then(reply => { if (reply?.ok) edit.selectInSketch([]); });
          return;
        }
        edit.setSketchTool(active ? null : each.id);
      };
      const key = sketchKey(each.id);
      return { id: each.id, label: each.label, hint: key ? `${each.label} (${key})` : undefined, icon: <Icon />,
        active, disabled: !sketch.state || edit.saving, onClick };
    };
    // A tool, or a family's button (the tool in hand of it, else the one last picked of it) with its flyout.
    const familyItem = id => {
      const family = SKETCH_FAMILIES[id];
      if (!family) return sketchItem(tool(id));
      const shown = family.includes(edit.sketchTool) ? edit.sketchTool : lastOfFamily[id] || id;
      const variants = family.map(each => sketchItem(tool(each)));
      const pick = each => setLastOfFamily(current => ({ ...current, [id]: each }));
      const name = FAMILY_NAMES[id] || tool(id).label;
      return { ...sketchItem(tool(shown)), id, variants, menu: <FamilyMenu label={name} items={variants} onPick={pick} /> };
    };
    const curves = new Set((sketch.state?.curves || []).map(curve => curve.id));
    const chosen = edit.sketchSelection.filter(id => curves.has(id));
    const allConstruction = chosen.length > 0 && chosen.every(id => sketch.state.curves.find(curve => curve.id === id)?.construction);
    const sketchStatus = sketch.state?.status || "Not solved";
    // Construction geometry, what is selected or what is drawn next; a switch, so the search presses it whether it is on or off.
    const toggleConstruction = () => (chosen.length ? void edit.sketchOp({ kind: "construction", items: chosen, on: !allConstruction })
      : edit.setConstruction(!edit.construction));
    // The features to make of the sketch, as NX names them; each finishes the sketch first, and subtracts by its Boolean in its dialog.
    const features = EDIT_COMMANDS.filter(command => command.sketch || command.sketches);
    const featureItem = command => ({ id: command.id, label: nxCommand(command), icon: commandIcon(command.id), disabled: edit.saving || !sketch.state,
      onClick: async () => { const reply = await edit.exitSketch(); if (reply?.ok) onCommand(command.id); } });
    const isSubtract = command => booleanOf(command.id)?.value === "subtract";
    const groups = [
      { title: "Sketch", items: [
        { id: "exit", label: "Exit Sketch", icon: <ExitSketchIcon />, disabled: edit.saving, onClick: () => void edit.exitSketch() },
        { id: "normal", label: "Normal To", icon: <NormalToIcon />, onClick: edit.lookNormalTo },
      ] },
      { title: "Curve", items: SKETCH_ENTITIES.map(id => familyItem(id)) },
      { title: "Edit Curve", items: SKETCH_MODIFY.map(id => familyItem(id)) },
      { title: "Constraints", items: [
        sketchItem(tool("dimension")),
        { id: "construction", label: "Construction Geometry", hint: "Construction Geometry (X)", icon: <ConstructionIcon />,
          active: chosen.length ? allConstruction : edit.construction,
          disabled: !sketch.state || edit.saving,
          description: chosen.length ? "Makes the selected entities construction geometry, or no longer" : "Draws what comes next as construction geometry",
          run: toggleConstruction, onClick: toggleConstruction },
      ] },
      // Each subtracts by its Boolean in its dialog, so the toolbar has the Subtract of each in its unite command's.
      { title: "Feature", items: features.filter(command => !isSubtract(command)).map(featureItem) },
    ];
    return ribbon("Sketch", groups, <>
      {statusLine(edit.saving ? "Solving" : `Editing ${sketch.name}`)}
      <span className={cn("shrink-0 text-micro", STATUS_CLASSES[sketchStatus] || "text-destructive")}>{sketchStatus}</span>
    </>, { sketching: true, tabs: workspaceTabs({ sketching: true }), active: "sketch", onPick: () => {},
      finds: () => searchable(groups, features.filter(isSubtract).map(featureItem)) });
  }

  const commandItem = command => {
    const open = edit.command === command.id || edit.command === booleanOf(command.id)?.other;
    // The search opens it as `onCommand` does, and not again one already open: an open Extrude is turned to its Subtract, not closed.
    return { id: command.id, label: nxCommand(command), icon: commandIcon(command.id), active: open, disabled: modelingOff,
      description: placingWords, run: () => { if (edit.command !== command.id) onCommand(command.id); },
      onClick: () => (open ? edit.close() : onCommand(command.id)) };
  };
  // Sketch, or Edit Sketch on the one selected: a new sketch waits for its plane, and a press again gives it up.
  const sketchCommand = { id: "sketch", label: sketchLabel, icon: <SketchIcon />, active: edit.picking, disabled: modelingOff,
    description: placingWords, onClick: () => (edit.picking ? edit.stopPicking() : onSketch()) };
  // A panel the ribbon opens beside the tree (Measure Bodies, Draft Analysis...), and closes again.
  const panelItem = (id, label, icon, what, disabled = edit.status !== "ready") => ({ id, label, icon, active: edit.inspecting === what, disabled,
    onClick: () => (edit.inspecting === what ? edit.stopInspecting() : edit.inspect(what)) });
  const viewerTool = id => (byId.has(id) ? [toolItem(byId.get(id))] : []);
  // What a SOLID_GROUPS item is, drawn: the Sketch command, a modeling command, or a tool of the viewer's strip (Select).
  const solidItems = id => {
    if (id === "sketch") return [sketchCommand];
    const command = EDIT_COMMANDS.find(each => each.id === id);
    if (command) return [commandItem(command)];
    return viewerTool(id);
  };
  const drawing = placing ? [] : state?.drawing ? [panelItem("drawing", "Drawing", <DrawingIcon />, "drawing")]
    : [{ id: "make-drawing", label: "Make Drawing", icon: <DrawingIcon />, disabled: edit.status !== "ready" || edit.saving,
      onClick: async () => { const reply = await edit.drawing({ make: true }); if (reply?.ok) edit.inspect("drawing"); } }];
  // An assembly: it places its parts (Assembly Constraints), or the view has parts to separate (Exploded Views).
  const tabs = workspaceTabs({ assembly: placing || byId.has("exploded"), drawing: drawing.length > 0 });
  const front = tabs.find(each => each.id === tab) || tabs[0];
  // Solid's groups (`SOLID_GROUPS`) show their most-used commands as buttons; the other tabs' groups are small
  // enough to show every one (`whole`). Every group's title is its menu all the same.
  const whole = (title, items) => ({ title, items, shown: items.length });
  const groupsOf = {
    solid: () => SOLID_GROUPS.map(group => ({ title: group.title, items: group.items.flatMap(solidItems), shown: group.shown, end: group.end })),
    sketch: () => [whole("Direct Sketch", [sketchCommand])],
    // Evaluate: what measures and checks the part, how it is seen, and the part's named sizes.
    inspect: () => [
      whole("Measure", [...viewerTool("measure"), panelItem("mass", "Mass Properties", <MassPropertiesIcon />, "mass")]),
      whole("Analyze", [
        ...(placing ? [] : [panelItem("draft-analysis", "Draft Analysis", <DraftAnalysisIcon />, "draft")]),
        panelItem("interference", "Interference Detection", <InterferenceIcon />, "interference"),
        ...(placing ? [] : [panelItem("compare", "Compare", <CompareIcon />, "compare")])]),
      whole("Section", viewerTool("clip")),
      whole("Display", [
        { id: "normal-to", label: "Normal To", icon: <NormalToIcon />,
          disabled: !onNormalTo, hint: "Orient View: look straight at the face or plane selected",
          description: onNormalTo ? undefined : "Select a flat face, or a plane in the design tree, to look straight at it.",
          onClick: () => onNormalTo?.() },
        ...(placing ? [] : [panelItem("appearance", "Appearance", <AppearanceIcon />, "appearance")])]),
      whole("Equations", [panelItem("expressions", "Equations", <ExpressionsIcon />, "expressions", false)]),
    ],
    // Assemble: an assembly's parts placed by Assembly Constraints, and its exploded views.
    assemble: () => [
      whole("Constraints", placing ? [panelItem("insert-components", "Insert Components", <InsertComponentIcon />, "insert", edit.status !== "ready" || edit.saving),
        panelItem("mate", "Mate", <MateIcon />, "mate", edit.status !== "ready" || edit.saving)] : []),
      whole("Exploded View", viewerTool("exploded")),
    ],
    // Drafting: the part's drawing.
    drafting: () => [whole("Sheet", drawing)],
  };
  return ribbon("Design", groupsOf[front.id]().filter(group => group.items.length), <>
    {statusLine(status, Boolean(state?.building?.error))}
    {state?.units ? <span className="shrink-0 text-micro text-muted-foreground/80">{unitWord(state.units)}</span> : null}
  </>, { tabs, active: front.id, onPick: setTab, key: `Design:${front.id}`,
    // Every tab's items, not the one in front; a command's Subtract is the Boolean of the unite command's dialog.
    finds: () => searchable(tabs.flatMap(each => groupsOf[each.id]()), EDIT_COMMANDS.filter(command => booleanOf(command.id)?.value === "subtract").map(commandItem)) });
}
