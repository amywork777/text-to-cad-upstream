import { useEffect, useMemo, useRef, useState } from "react";
import { ScrollArea } from "@text-to-cad/ui/primitives/scroll-area";
import { TooltipHint } from "@text-to-cad/ui/primitives/tooltip";
import { cn } from "@text-to-cad/ui/utils";
import { WORKSPACE_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { VIEWPORT_CUBE_BOTTOM } from "../../kit/shell/viewportLayout.js";
import { AUTHOR_DOT_CLASS, AUTHOR_WORDS } from "./authors.js";
import { FeatureIcon } from "./featureIcons.jsx";
import { slotAtX, timelineItems } from "./timeline.js";

// The timeline's measures, in rem: a tile for each icon; the gap between two items, room for the marker, which
// stands in it; the closer gap between a feature and the sketch it was made from, where no marker stands; and
// the padding at the ends. The marker's place is arithmetic on them, so no layout is read to draw it.
const TILE = 1.75, GAP = 0.5, PAIR = 0.25, PAD = 0.5;
const MEASURES = Object.freeze({ "--tl-tile": `${TILE}rem`, "--tl-gap": `${GAP}rem`, "--tl-pair": `${PAIR}rem`, "--tl-pad": `${PAD}rem` });

/** What an icon's tooltip adds under its title: that it is set aside, and who made it. */
const notesOf = icon => [icon.feature.suppressed ? "Suppressed" : "", AUTHOR_WORDS[icon.author] || ""].filter(Boolean);

/**
 * Where the gap before the item at `slot` begins, in rem from the list's left edge: past the padding and the
 * items before it, each one tile, or two with the closer gap between them when it has the sketch it was made
 * from, and the gap that follows it, less the gap itself.
 */
const gapBefore = (items, slot) => items.slice(0, slot).reduce((x, item) => x + (item.sketch ? 2 * TILE + PAIR : TILE) + GAP, PAD - GAP);

/**
 * The rollback bar's marker: the design tree's bar laid along the timeline, dragged back to a gap
 * between items (or moved an item at a time with the arrow keys) to show the part as it was there.
 * `index` is the item it stands before (`count`: past the last). While dragged it follows the pointer
 * from gap to gap and `onPreview` says which gap it is in (null: the one it began in), which draws the
 * timeline again and never the model; the part is rolled back when it is let go (`onMove`). `left` is
 * where the gap it is drawn in begins, `centersOf` the items' centres in the pointer's own coordinates,
 * measured as the press lands.
 */
function RollbackMarker({ index, left, count, label, disabled, centersOf, onPreview, onMove }) {
  const drag = useRef(null);
  // Taken away mid-drag (the part is being read again), it leaves no gap to draw it in.
  useEffect(() => () => onPreview(null), [onPreview]);
  // Never above the first item: that would leave no part.
  const place = target => Math.max(1, Math.min(count, target));
  return <TooltipHint content="Rollback bar's marker: drag it back to see the part as it was there" side="top" disabled={disabled}>
    <div role="slider" aria-label="Rollback bar's marker" aria-orientation="horizontal" aria-valuemin={1} aria-valuemax={count}
      aria-valuenow={index} aria-valuetext={label} aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : 0}
      data-cad-edit-rollback-marker=""
      className={cn("group/marker absolute bottom-2 left-0 top-1.5 z-10 flex touch-none justify-center focus-visible:outline-none",
        disabled ? "cursor-default opacity-50" : "cursor-grab active:cursor-grabbing")}
      style={{ width: `${GAP}rem`, transform: `translateX(${left}rem)` }}
      onPointerDown={event => {
        if (disabled || event.button !== 0) return;
        // No text selection while dragging; focus taken by hand, so the arrow keys move it after a click.
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { centers: centersOf(), at: index };
      }}
      onPointerMove={event => {
        if (!drag.current) return;
        const at = place(slotAtX(event.clientX, drag.current.centers));
        if (at !== drag.current.at) { drag.current.at = at; onPreview(at === index ? null : at); }
      }}
      onPointerUp={event => {
        if (!drag.current) return;
        const { at } = drag.current;
        drag.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
        onPreview(null);
        if (at !== index) onMove(at);
      }}
      onPointerCancel={() => { drag.current = null; onPreview(null); }}
      onKeyDown={event => {
        if (disabled) return;
        const target = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 1, End: count }[event.key];
        if (target === undefined) return;
        event.preventDefault();
        event.stopPropagation();
        if (place(target) !== index) onMove(place(target));
      }}>
      <span className="h-full w-[3px] rounded-full bg-info/70 group-hover/marker:bg-info group-focus-visible/marker:bg-info" />
    </div>
  </TooltipHint>;
}

/**
 * One icon of the timeline: a feature's or the sketch it was made from (`icon`, shaped as `timelineItems`
 * gives either). A click selects it (`onSelect`, given its id) and a double-click edits it (`onOpen`);
 * `out` draws it as the part will not have it, and a suppressed one is drawn so too. Under the pointer it
 * is the workspace's pale blue, selected its deeper one, and nothing else changes.
 */
function TimelineIcon({ icon, selected, out, onSelect, onOpen }) {
  const notes = notesOf(icon);
  return <TooltipHint side="top" content={<>
    {icon.title}{notes.map(note => <span key={note} className="block text-muted-foreground">{note}</span>)}
  </>}>
    <button type="button" aria-label={icon.title} aria-description={notes.join(". ") || undefined} aria-pressed={selected}
      data-cad-timeline-item={icon.id} data-rolled-back={out ? "" : undefined} data-suppressed={icon.feature.suppressed ? "" : undefined}
      className="group/item flex shrink-0 flex-col items-center gap-0.5 focus-visible:outline-none"
      onClick={() => onSelect(icon.id)} onDoubleClick={() => onOpen(icon)}>
      <span className={cn("flex size-(--tl-tile) items-center justify-center rounded-sm border border-border [&_svg]:m-0 [&_svg]:size-5 group-focus-visible/item:ring-2 group-focus-visible/item:ring-ring/45",
        selected ? "bg-cad-ws-selected" : "bg-background group-hover/item:bg-cad-ws-hover")}>
        <span className="flex group-data-[rolled-back]/item:opacity-50 group-data-[suppressed]/item:opacity-50"><FeatureIcon kind={icon.kind} /></span>
      </span>
      <span data-cad-timeline-author={icon.author ?? undefined} className={cn("size-1.5 rounded-full", icon.author && AUTHOR_DOT_CLASS[icon.author])} />
    </button>
  </TooltipHint>;
}

/**
 * Edit mode's timeline, as Fusion lays one along the bottom of its window: every feature of the part as
 * its icon, in the order the design tree lists them (`timeline.js`; a sketch of its own among them), the
 * sketch a feature was made from as an icon just before it, each named by its title on hover, with a dot
 * under it for who made it (the agent's purple, yours grey, none where it is not known: `edit.state.authors`;
 * a sketch carries its feature's). A click selects an icon, a sketch by the id the design tree selects it
 * by, and a double-click edits it: Edit Feature on a feature a command made (`edit.editFeature`), Edit
 * Sketch on a sketch (`onEditSketch`). The rollback bar's marker stands after the last item the part still
 * has, and is dragged back to roll the part back to there, the same rollback as the design tree's bar
 * and its Make Current Feature (`edit.rollTo`); a feature and its sketch go together, so it never stands
 * between them. What the marker leaves out, and what is suppressed, is greyed. It floats over the canvas
 * on the workspace's white card, an inset in from the frame's `bottomDock` (a dock with no height of its
 * own, kept clear of the cube), on the cube's line, and draws nothing for a part with no features or for
 * an assembly. CAD mode (`useXbfCadMode.jsx`) does not hand it to the frame while the drawing's sheet is up.
 *
 * @param {{ edit: ReturnType<typeof import("./useEditMode.js").useEditMode>,
 *   tree: ReturnType<typeof import("./editMode.js").featureTree>, onEditSketch?: (sketch: object) => void }} props
 */
export default function EditTimeline({ edit, tree, onEditSketch = () => {} }) {
  const authors = edit.state?.authors;
  const { items, marker } = useMemo(() => timelineItems(tree, edit.bar, authors), [tree, edit.bar, authors]);
  // The gap the marker is dragged to, while it is: the items past it are drawn as the part will have them.
  const [dragged, setDragged] = useState(null);
  const listRef = useRef(null);
  if (!items.length) return null;
  const disabled = edit.saving || edit.status !== "ready";
  // As in the design tree, nothing is edited or rolled back while a sketch is open or a change is on its way.
  const busy = disabled || Boolean(edit.sketch);
  const slot = dragged ?? marker;
  // The marker steps over whole items, a feature with its sketch: it is their middles a pointer is read against.
  const centersOf = () => [...(listRef.current?.querySelectorAll("[data-cad-timeline-group]") || [])].map(group => {
    const box = group.getBoundingClientRect();
    return box.left + box.width / 2;
  });
  // A double-click edits: the command that made a feature, or a sketch, its own or the one a feature was made from.
  const open = icon => {
    if (icon.kind === "Sketch") { if (!disabled) onEditSketch(icon.feature.sketch); return; }
    if (icon.feature.edit && !busy) edit.editFeature(icon.feature);
  };
  // The card is a box of its own around the ScrollArea: the ScrollArea's root sets its position inline, so it
  // cannot be placed by a class.
  return <div role="group" aria-label="Timeline" data-cad-edit-timeline=""
    className={cn(WORKSPACE_SURFACE_CLASS, "pointer-events-auto absolute inset-x-2 flex select-none overflow-hidden")} style={{ bottom: VIEWPORT_CUBE_BOTTOM }}>
    <ScrollArea orientation="horizontal" className="min-w-0 flex-1">
      <div ref={listRef} className="relative flex items-start gap-(--tl-gap) px-(--tl-pad) pb-2 pt-1.5" style={MEASURES}>
        {items.map((item, index) => {
          // A feature and its sketch are rolled back together, and drawn so while the marker is dragged past them.
          const out = dragged === null ? item.rolledBack : index >= dragged;
          return <div key={item.id} data-cad-timeline-group={item.id} className="flex shrink-0 gap-(--tl-pair)">
            {[item.sketch, item].filter(Boolean).map(icon => (
              <TimelineIcon key={icon.id} icon={icon} selected={edit.selected === icon.id} out={out} onSelect={edit.select} onOpen={open} />))}
          </div>;
        })}
        {items.length > 1 && edit.status === "ready" ? <RollbackMarker index={marker} left={gapBefore(items, slot)} count={items.length}
          label={marker >= items.length ? "At the end" : `Above ${items[marker].title}`} disabled={busy}
          centersOf={centersOf} onPreview={setDragged}
          onMove={index => void edit.rollTo(index >= items.length ? null : items[index].id)} /> : null}
      </div>
    </ScrollArea>
  </div>;
}
